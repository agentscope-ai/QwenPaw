"""Tests for the chat-facing embedded ReMe job gateway."""

# pylint: disable=protected-access

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.asyncio
async def test_list_reme_actions_only_returns_servable_jobs() -> None:
    manager = _manager_with_jobs(
        {
            "status": _job(),
            "background": _job(enable_serve=False),
        },
    )

    actions = await manager.list_reme_actions()

    assert set(actions) == {"status"}
    assert actions["status"]["description"] == "test job"


@pytest.mark.asyncio
async def test_run_reme_action_validates_and_refreshes_llm_jobs() -> None:
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

    await manager.run_reme_action("auto_dream", hint="recent topics")

    manager._run_reme_job.assert_awaited_once_with(
        "auto_dream",
        needs_llm=True,
        raise_on_error=True,
        hint="recent topics",
    )


@pytest.mark.asyncio
async def test_run_reme_action_rejects_unknown_and_invalid_arguments() -> None:
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
        await manager.run_reme_action("search")
    with pytest.raises(ValueError, match="Unknown argument"):
        await manager.run_reme_action("search", query="x", extra=True)
    with pytest.raises(ValueError, match="must be integer"):
        await manager.run_reme_action("search", query="x", limit="2")
    with pytest.raises(ValueError, match="must be one of"):
        await manager.run_reme_action("search", query="x", limit=3)
    with pytest.raises(ValueError, match="Unknown or unavailable"):
        await manager.run_reme_action("delete", path="x")

    manager._run_reme_job.assert_not_awaited()
