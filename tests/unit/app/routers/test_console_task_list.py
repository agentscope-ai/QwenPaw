# -*- coding: utf-8 -*-
"""Unit tests for the background task list API (issue #7056).

``GET /console/chat/tasks`` returns status summaries for every in-flight
background chat task in one request, so callers no longer need to poll
each task id individually.
"""

# pylint: disable=protected-access
import pytest

from qwenpaw.app.routers import console


@pytest.mark.asyncio
async def test_list_tasks_empty() -> None:
    """An empty task store yields an empty mapping."""
    console._bg_tasks.clear()
    result = await console.list_console_chat_tasks()
    assert result == {"tasks": {}}


@pytest.mark.asyncio
async def test_list_tasks_mixed_statuses() -> None:
    """Running and finished tasks both appear with their own fields."""
    console._bg_tasks.clear()
    console._bg_tasks["task-running"] = console._BackgroundTask(
        status="running",
        started_at=100.0,
    )
    console._bg_tasks["task-done"] = console._BackgroundTask(
        status="finished",
        started_at=50.0,
        finished_at=60.0,
        result={"status": "completed", "output": ["ok"]},
    )
    try:
        result = await console.list_console_chat_tasks()
    finally:
        console._bg_tasks.clear()

    tasks = result["tasks"]
    assert set(tasks.keys()) == {"task-running", "task-done"}

    running = tasks["task-running"]
    assert running["status"] == "running"
    assert running["started_at"] == 100.0
    assert "finished_at" not in running
    assert "result" not in running

    done = tasks["task-done"]
    assert done["status"] == "finished"
    assert done["finished_at"] == 60.0
    assert done["result"]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_tasks_matches_single_task_shape() -> None:
    """Each list entry mirrors the single-task endpoint response shape."""
    console._bg_tasks.clear()
    console._bg_tasks["task-x"] = console._BackgroundTask(
        status="finished",
        started_at=1.0,
        finished_at=2.0,
        result={"status": "completed"},
    )
    try:
        listed = await console.list_console_chat_tasks()
        single = await console.get_console_chat_task("task-x")
    finally:
        console._bg_tasks.clear()

    entry = listed["tasks"]["task-x"]
    assert entry["status"] == single["status"]
    assert entry["started_at"] == single["started_at"]
    assert entry["result"] == single["result"]
