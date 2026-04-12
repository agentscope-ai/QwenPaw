# -*- coding: utf-8 -*-
"""Tests for GitHub issue #3275:

Background tasks dispatched via ``--background`` (i.e. submitted through the
AgentApp ``/api/agent/process/task`` endpoint) were unexpectedly cancelled when
an agent workspace underwent a reload.

Root cause
----------
``MultiAgentManager._graceful_stop_old_instance()`` only consulted
``Workspace.task_tracker`` (CoPaw's internal ``TaskTracker``).  Background
tasks submitted through ``AgentApp`` were tracked in
``AgentApp.active_tasks`` (managed by ``agentscope_runtime``'s
``TaskEngineMixin``) and were *invisible* to the graceful-shutdown check.

Fix (Option A)
--------------
``DynamicMultiAgentRunner.stream_query()`` now registers each request with
the workspace's ``TaskTracker`` via ``register_external_task()`` /
``unregister_external_task()``.  This makes AgentApp-dispatched tasks visible
to ``has_active_tasks()`` during graceful shutdown.

This file contains:
- Reproduction tests proving the original bug exists without the fix
- Verification tests proving the fix resolves the issue
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Import TaskTracker directly (bypass heavy __init__.py chains that pull in
# agentscope, numpy, etc.).
# ---------------------------------------------------------------------------


def _import_module_directly(module_name: str, file_path: str) -> ModuleType:
    """Import a single module file without triggering package __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_SRC = Path(__file__).resolve().parents[3] / "src"

_task_tracker_mod = _import_module_directly(
    "copaw.app.runner.task_tracker",
    str(_SRC / "copaw" / "app" / "runner" / "task_tracker.py"),
)
TaskTracker = _task_tracker_mod.TaskTracker


# ---------------------------------------------------------------------------
# Minimal stubs that satisfy MultiAgentManager / Workspace contracts without
# needing a full configuration file or running services.
# ---------------------------------------------------------------------------


class StubServiceManager:
    """Minimal stub for ServiceManager."""

    def __init__(self):
        self.services: dict[str, Any] = {}

    def get_reusable_services(self) -> dict:
        return {}


class StubWorkspace:
    """Minimal stand-in for ``Workspace``.

    Attributes:
        task_tracker: A real ``TaskTracker`` instance.
        stopped: Set to ``True`` when ``stop()`` is called.
    """

    def __init__(self, agent_id: str, workspace_dir: str):
        self.agent_id = agent_id
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._task_tracker = TaskTracker()
        self._service_manager = StubServiceManager()
        self._started = True
        self._manager = None
        self.stopped = False
        self.runner = MagicMock()

    @property
    def task_tracker(self) -> TaskTracker:
        return self._task_tracker

    def set_manager(self, manager: Any) -> None:
        self._manager = manager

    async def start(self) -> None:
        self._started = True

    async def stop(self, final: bool = True) -> None:
        self.stopped = True
        self._started = False


# ---------------------------------------------------------------------------
# Standalone reimplementation of the graceful-stop logic from
# MultiAgentManager._graceful_stop_old_instance() — extracted here to avoid
# importing the full module with all its heavy dependencies.
# This mirrors lines 91-186 of multi_agent_manager.py exactly.
# ---------------------------------------------------------------------------


async def graceful_stop_old_instance(
    old_instance: StubWorkspace,
    agent_id: str,
    cleanup_tasks: set,
) -> bool:
    """Return True if stopped immediately, False if delayed cleanup scheduled.

    Reproduces the exact logic of
    ``MultiAgentManager._graceful_stop_old_instance()``.
    """
    has_active = await old_instance.task_tracker.has_active_tasks()

    if has_active:
        active_tasks = await old_instance.task_tracker.list_active_tasks()

        async def delayed_cleanup():
            try:
                completed = await old_instance.task_tracker.wait_all_done(
                    timeout=60.0,
                )
                await old_instance.stop(final=False)
            except Exception:
                pass

        cleanup_task = asyncio.create_task(delayed_cleanup())
        cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(lambda t: cleanup_tasks.discard(t))
        return False  # delayed
    else:
        await old_instance.stop(final=False)
        return True  # immediate


# ---------------------------------------------------------------------------
# Simulated AgentApp background task state (mirrors TaskEngineMixin)
# ---------------------------------------------------------------------------


def _make_agent_app_active_tasks() -> dict[str, dict]:
    """Return an ``active_tasks`` dict with one in-flight background task.

    This mirrors what ``AgentApp`` / ``TaskEngineMixin`` would hold when a
    background task was submitted via ``POST /api/agent/process/task``.
    """
    return {
        "task-bg-001": {
            "task_id": "task-bg-001",
            "status": "running",
            "queue": "stream_query",
            "submitted_at": 1000.0,
            "started_at": 1001.0,
        },
    }


# ===========================================================================
# Part 1: Bug reproduction tests (prove the original problem)
# ===========================================================================


@pytest.mark.asyncio
async def test_unregistered_task_causes_immediate_stop():
    """Without external task registration, the old workspace is stopped
    immediately even though a background task is still running.

    This demonstrates the original bug path: when tasks are NOT registered
    with the TaskTracker, ``_graceful_stop_old_instance`` considers the
    workspace idle.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        # CoPaw TaskTracker is empty (no registered tasks)
        assert await old_ws.task_tracker.has_active_tasks() is False

        # AgentApp has a running background task (but it's not registered)
        agent_app_tasks = _make_agent_app_active_tasks()
        assert any(
            t["status"] in ("submitted", "running")
            for t in agent_app_tasks.values()
        )

        # Graceful stop runs — stops immediately (the bug path)
        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )

        assert stopped_immediately is True, (
            "Without external task registration, the workspace is stopped "
            "immediately because has_active_tasks() returns False."
        )
        assert old_ws.stopped is True


@pytest.mark.asyncio
async def test_reload_kills_unregistered_background_task():
    """End-to-end reproduction: agent reload kills a background task that is
    NOT registered with the workspace's TaskTracker.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        async def slow_background_task():
            await asyncio.sleep(60)
            return "completed"

        bg_task = asyncio.create_task(slow_background_task())
        await asyncio.sleep(0)
        assert not bg_task.done()

        # TaskTracker sees nothing — the task was not registered.
        assert await old_ws.task_tracker.has_active_tasks() is False

        # Graceful stop: immediate (the bug).
        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )
        assert stopped_immediately is True
        assert old_ws.stopped is True

        # Clean up the orphaned task.
        bg_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bg_task
        assert bg_task.cancelled()


# ===========================================================================
# Part 2: Fix verification tests
# ===========================================================================


@pytest.mark.asyncio
async def test_register_external_task_makes_tracker_active():
    """``register_external_task`` makes the task visible to
    ``has_active_tasks()`` and ``list_active_tasks()``.
    """
    tracker = TaskTracker()

    assert await tracker.has_active_tasks() is False
    assert await tracker.list_active_tasks() == []

    await tracker.register_external_task("ext-001")

    assert await tracker.has_active_tasks() is True
    assert await tracker.list_active_tasks() == ["ext-001"]


@pytest.mark.asyncio
async def test_unregister_external_task_clears_tracker():
    """``unregister_external_task`` removes the task and makes the tracker
    report idle again.
    """
    tracker = TaskTracker()
    await tracker.register_external_task("ext-001")
    assert await tracker.has_active_tasks() is True

    await tracker.unregister_external_task("ext-001")

    assert await tracker.has_active_tasks() is False
    assert await tracker.list_active_tasks() == []


@pytest.mark.asyncio
async def test_unregister_external_task_is_idempotent():
    """Calling ``unregister_external_task`` twice does not raise."""
    tracker = TaskTracker()
    await tracker.register_external_task("ext-001")
    await tracker.unregister_external_task("ext-001")
    # Second call should be a no-op
    await tracker.unregister_external_task("ext-001")
    assert await tracker.has_active_tasks() is False


@pytest.mark.asyncio
async def test_register_external_task_duplicate_is_safe():
    """Registering the same run_key twice is idempotent."""
    tracker = TaskTracker()
    await tracker.register_external_task("ext-001")
    await tracker.register_external_task("ext-001")

    assert await tracker.list_active_tasks() == ["ext-001"]

    await tracker.unregister_external_task("ext-001")
    assert await tracker.has_active_tasks() is False


@pytest.mark.asyncio
async def test_multiple_external_tasks():
    """Multiple external tasks can coexist."""
    tracker = TaskTracker()
    await tracker.register_external_task("ext-001")
    await tracker.register_external_task("ext-002")

    active = await tracker.list_active_tasks()
    assert sorted(active) == ["ext-001", "ext-002"]

    await tracker.unregister_external_task("ext-001")
    assert await tracker.list_active_tasks() == ["ext-002"]

    await tracker.unregister_external_task("ext-002")
    assert await tracker.has_active_tasks() is False


@pytest.mark.asyncio
async def test_wait_all_done_waits_for_external_tasks():
    """``wait_all_done`` blocks until external tasks are unregistered."""
    tracker = TaskTracker()
    await tracker.register_external_task("ext-001")

    async def unregister_after_delay():
        await asyncio.sleep(0.2)
        await tracker.unregister_external_task("ext-001")

    asyncio.create_task(unregister_after_delay())

    completed = await tracker.wait_all_done(timeout=5.0)
    assert completed is True
    assert await tracker.has_active_tasks() is False


@pytest.mark.asyncio
async def test_external_tasks_coexist_with_internal_tasks():
    """External tasks and internal streaming tasks are both visible."""
    tracker = TaskTracker()

    # Register an external task
    await tracker.register_external_task("ext-001")

    # Start an internal streaming task
    async def stream(payload):
        await asyncio.sleep(0.2)
        yield "data: done\n\n"

    queue, is_new = await tracker.attach_or_start("chat-1", {}, stream)
    assert is_new is True

    active = await tracker.list_active_tasks()
    assert sorted(active) == ["chat-1", "ext-001"]

    # Unregister external — internal still active
    await tracker.unregister_external_task("ext-001")
    assert await tracker.has_active_tasks() is True
    assert await tracker.list_active_tasks() == ["chat-1"]

    # Wait for internal to finish
    completed = await tracker.wait_all_done(timeout=5.0)
    assert completed is True
    assert await tracker.has_active_tasks() is False


@pytest.mark.asyncio
async def test_registered_external_task_delays_graceful_stop():
    """When a background task IS registered with the TaskTracker via
    ``register_external_task``, ``_graceful_stop_old_instance`` schedules
    delayed cleanup instead of stopping immediately.

    This is the core fix for issue #3275.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        # Simulate what the fixed DynamicMultiAgentRunner.stream_query()
        # now does: register the background task with the TaskTracker.
        await old_ws.task_tracker.register_external_task("ext-bg-001")
        assert await old_ws.task_tracker.has_active_tasks() is True

        # Graceful stop should now detect the active task.
        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )

        # NOT stopped immediately — delayed cleanup was scheduled.
        assert stopped_immediately is False, (
            "With external task registered, graceful stop should delay "
            "rather than stop immediately."
        )
        assert old_ws.stopped is False, (
            "Workspace should still be running while external task is active"
        )
        assert len(cleanup_tasks) == 1, (
            "Expected delayed cleanup task to be scheduled"
        )

        # Simulate the background task completing (unregister it).
        await old_ws.task_tracker.unregister_external_task("ext-bg-001")

        # Wait for delayed cleanup to finish.
        await asyncio.sleep(1.0)

        # Now the workspace should have been stopped by the cleanup task.
        assert old_ws.stopped is True, (
            "Workspace should be stopped after external task completes"
        )

        # Clean up
        for task in list(cleanup_tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


@pytest.mark.asyncio
async def test_copaw_tracked_task_delays_shutdown():
    """Verify that tasks tracked by CoPaw's ``TaskTracker`` (internal
    streaming) DO delay the shutdown — proving the mechanism was always
    correct for internal tasks.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        completion_event = asyncio.Event()

        async def slow_stream(payload):
            await asyncio.sleep(0.3)
            completion_event.set()
            yield "data: done\n\n"

        queue, is_new = await old_ws.task_tracker.attach_or_start(
            "chat-123",
            {},
            slow_stream,
        )
        assert is_new is True
        assert await old_ws.task_tracker.has_active_tasks() is True

        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )

        assert stopped_immediately is False
        assert len(cleanup_tasks) == 1

        await completion_event.wait()
        await asyncio.sleep(0.5)

        assert old_ws.stopped is True

        for task in list(cleanup_tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
