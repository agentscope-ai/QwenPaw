"""Tests for the chat-facing embedded ReMe job gateway."""

# pylint: disable=protected-access

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.agents.memory.action_provider import MemoryActionProvider
from qwenpaw.agents.memory.dummy import NoopMemoryManager
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _manager_with_jobs(jobs):
    manager = object.__new__(ReMeLightMemoryManager)
    manager._reme = SimpleNamespace(
        is_started=True,
        context=SimpleNamespace(jobs=jobs),
    )

    @asynccontextmanager
    async def lease():
        yield

    manager._reme_job_lease = lease
    manager._run_reme_job = AsyncMock(
        return_value=SimpleNamespace(success=True, answer="ok", metadata={}),
    )
    return manager


def _job(*, parameters=None, enable_serve=True):
    return SimpleNamespace(
        description="test job",
        parameters=parameters or {"type": "object", "properties": {}},
        enable_serve=enable_serve,
    )


def test_only_action_backends_expose_action_provider(tmp_path) -> None:
    manager = _manager_with_jobs({})
    noop = NoopMemoryManager(str(tmp_path), "test-agent")

    assert isinstance(manager, MemoryActionProvider)
    assert not isinstance(noop, MemoryActionProvider)


@pytest.mark.asyncio
async def test_list_actions_only_returns_servable_jobs() -> None:
    manager = _manager_with_jobs(
        {
            "status": _job(),
            "background": _job(enable_serve=False),
        },
    )

    actions = await manager.list_actions()

    assert set(actions) == {"status"}
    assert actions["status"]["description"] == "test job"


@pytest.mark.asyncio
async def test_run_action_validates_and_refreshes_llm_jobs() -> None:
    manager = _manager_with_jobs(
        {
            "auto_dream": _job(
                parameters={
                    "type": "object",
                    "properties": {"hint": {"type": "string"}},
                },
            ),
        },
    )

    await manager.run_action("auto_dream", hint="recent topics")

    manager._run_reme_job.assert_awaited_once_with(
        "auto_dream",
        needs_llm=True,
        raise_on_error=True,
        hint="recent topics",
    )


@pytest.mark.asyncio
async def test_run_action_rejects_unknown_and_invalid_arguments() -> None:
    manager = _manager_with_jobs(
        {
            "search": _job(
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "enum": [1, 2]},
                    },
                    "required": ["query"],
                },
            ),
        },
    )

    with pytest.raises(ValueError, match="Missing required"):
        await manager.run_action("search")
    with pytest.raises(ValueError, match="Unknown argument"):
        await manager.run_action("search", query="x", extra=True)
    with pytest.raises(ValueError, match="must be integer"):
        await manager.run_action("search", query="x", limit="2")
    with pytest.raises(ValueError, match="must be one of"):
        await manager.run_action("search", query="x", limit=3)
    with pytest.raises(ValueError, match="Unknown or unavailable"):
        await manager.run_action("delete", path="x")

    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_action_delegates_reindex_lifecycle() -> None:
    manager = _manager_with_jobs(
        {
            "reindex": _job(
                parameters={
                    "type": "object",
                    "properties": {"scope": {"type": "string"}},
                },
            ),
        },
    )
    manager._rebuild_index = AsyncMock(return_value="reindexed")

    response = await manager.run_action("reindex", scope="embedding")

    assert response == "reindexed"
    manager._rebuild_index.assert_awaited_once_with("embedding")
    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_memory_uses_the_action_provider() -> None:
    manager = _manager_with_jobs(
        {
            "auto_memory": _job(
                parameters={
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array"},
                        "session_id": {"type": "string"},
                        "memory_hint": {"type": "string"},
                    },
                    "required": ["messages"],
                },
            ),
        },
    )
    message = MagicMock(metadata={})
    message.model_dump.return_value = {"role": "user", "content": "hello"}

    result = await manager.auto_memory(
        [message],
        session_id="session-1",
        memory_hint="remember this",
    )

    assert result == "ok"
    call = manager._run_reme_job.await_args
    assert call.args == ("auto_memory",)
    assert call.kwargs["needs_llm"] is True
    assert call.kwargs["raise_on_error"] is True
    assert call.kwargs["messages"] == [
        {"role": "user", "content": "hello"},
    ]
    assert call.kwargs["session_id"].startswith("qpsid_sha256_")
    assert call.kwargs["memory_hint"] == "remember this"
