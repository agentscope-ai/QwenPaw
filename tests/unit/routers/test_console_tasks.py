# -*- coding: utf-8 -*-
"""Unit tests for console background chat task bookkeeping."""
from __future__ import annotations

import pytest

from qwenpaw.app.routers import console


def setup_function() -> None:
    console._CHAT_TASKS.clear()
    console._CHAT_RUNTIME_TASKS.clear()


def teardown_function() -> None:
    console._CHAT_TASKS.clear()
    console._CHAT_RUNTIME_TASKS.clear()


def test_prune_finished_chat_tasks_keeps_recent_records(monkeypatch) -> None:
    monkeypatch.setattr(console, "_MAX_FINISHED_CHAT_TASKS", 2)
    console._CHAT_TASKS.update(
        {
            "old": {
                "task_id": "old",
                "agent_id": "default",
                "status": "finished",
                "finished_at": "2026-01-01T00:00:00+00:00",
            },
            "middle": {
                "task_id": "middle",
                "agent_id": "default",
                "status": "finished",
                "finished_at": "2026-01-02T00:00:00+00:00",
            },
            "new": {
                "task_id": "new",
                "agent_id": "default",
                "status": "finished",
                "finished_at": "2026-01-03T00:00:00+00:00",
            },
            "running": {
                "task_id": "running",
                "agent_id": "default",
                "status": "running",
            },
        },
    )

    console._prune_finished_chat_tasks()

    assert set(console._CHAT_TASKS) == {"middle", "new", "running"}


@pytest.mark.asyncio
async def test_finished_chat_task_status_is_dropped_after_read(
    monkeypatch,
) -> None:
    class _Workspace:
        agent_id = "default"

    async def _fake_get_agent_for_request(_request):
        return _Workspace()

    monkeypatch.setattr(console, "get_agent_for_request", _fake_get_agent_for_request)
    console._CHAT_TASKS["task-1"] = {
        "task_id": "task-1",
        "agent_id": "default",
        "session_id": "session-1",
        "status": "finished",
        "result": {"status": "completed"},
    }

    result = await console.get_console_chat_task_status("task-1", object())

    assert result == {
        "task_id": "task-1",
        "session_id": "session-1",
        "status": "finished",
        "result": {"status": "completed"},
    }
    assert "task-1" not in console._CHAT_TASKS


@pytest.mark.asyncio
async def test_running_chat_task_status_is_retained(monkeypatch) -> None:
    class _Workspace:
        agent_id = "default"

    async def _fake_get_agent_for_request(_request):
        return _Workspace()

    monkeypatch.setattr(console, "get_agent_for_request", _fake_get_agent_for_request)
    console._CHAT_TASKS["task-1"] = {
        "task_id": "task-1",
        "agent_id": "default",
        "session_id": "session-1",
        "status": "running",
    }

    result = await console.get_console_chat_task_status("task-1", object())

    assert result["status"] == "running"
    assert "task-1" in console._CHAT_TASKS
