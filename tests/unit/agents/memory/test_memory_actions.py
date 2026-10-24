# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for optional memory actions exposed by ReMe."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _job(*, parameters=None, enable_serve=True):
    return SimpleNamespace(
        description="test action",
        parameters=parameters or {"type": "object", "properties": {}},
        enable_serve=enable_serve,
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


@pytest.mark.asyncio
async def test_list_actions_only_exposes_servable_jobs() -> None:
    manager = _manager_with_jobs(
        {"status": _job(), "background": _job(enable_serve=False)},
    )

    actions = await manager.list_actions()

    assert set(actions) == {"status", "undo_reindex"}
    assert actions["status"]["description"] == "test action"


@pytest.mark.asyncio
async def test_run_action_validates_arguments_before_execution() -> None:
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

    with pytest.raises(ValueError, match="'query' is a required property"):
        await manager.run_action("search")
    with pytest.raises(ValueError, match="Additional properties"):
        await manager.run_action("search", query="x", extra=True)
    with pytest.raises(ValueError, match="is not of type 'integer'"):
        await manager.run_action("search", query="x", limit="2")
    with pytest.raises(ValueError, match="is not one of"):
        await manager.run_action("search", query="x", limit=3)

    manager._run_reme_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_action_honors_nested_json_schema_constraints() -> None:
    manager = _manager_with_jobs(
        {
            "traverse": _job(
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "oneOf": [
                                {"type": "string", "pattern": r"^memory/"},
                                {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                },
                            ],
                        },
                        "depth": {"type": "integer", "minimum": 0},
                    },
                },
            ),
        },
    )

    with pytest.raises(ValueError, match="should be non-empty"):
        await manager.run_action("traverse", path=[])
    with pytest.raises(ValueError, match="less than the minimum"):
        await manager.run_action("traverse", path="memory/day.md", depth=-1)

    await manager.run_action(
        "traverse",
        path=["memory/day.md"],
        depth=1,
    )
    manager._run_reme_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_action_marks_llm_jobs_and_rejects_hidden_jobs() -> None:
    manager = _manager_with_jobs(
        {
            "auto_dream": _job(
                parameters={
                    "type": "object",
                    "properties": {"hint": {"type": "string"}},
                },
            ),
            "hidden": _job(enable_serve=False),
        },
    )

    await manager.run_action("auto_dream", hint="recent topics")

    manager._run_reme_job.assert_awaited_once_with(
        "auto_dream",
        needs_llm=True,
        raise_on_error=True,
        lifecycle_locked=True,
        hint="recent topics",
    )
    with pytest.raises(ValueError, match="Unknown or unavailable"):
        await manager.run_action("hidden")


@pytest.mark.asyncio
async def test_run_action_routes_host_managed_embedding_actions() -> None:
    manager = _manager_with_jobs(
        {
            "reindex": _job(
                parameters={
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "enum": ["all", "bm25", "embedding"],
                        },
                    },
                },
            ),
        },
    )
    embedding = SimpleNamespace(
        rebuild_index=AsyncMock(
            return_value=SimpleNamespace(success=True, answer="rebuilt"),
        ),
        undo_reindex=AsyncMock(return_value={"model_name": "indexed"}),
    )
    manager._embedding_service = lambda: embedding

    rebuilt = await manager.run_action("reindex", scope="embedding")
    restored = await manager.run_action("undo_reindex")

    assert rebuilt.answer == "rebuilt"
    assert restored.success is True
    assert restored.answer == {"model_name": "indexed"}
    embedding.rebuild_index.assert_awaited_once_with("embedding")
    embedding.undo_reindex.assert_awaited_once_with()
