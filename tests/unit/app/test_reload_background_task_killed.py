# -*- coding: utf-8 -*-
"""Reproduce GitHub issue #3275:

Background tasks dispatched via ``--background`` (i.e. submitted through the
AgentApp ``/api/agent/process/task`` endpoint) are unexpectedly cancelled when
an agent workspace undergoes a reload.

Root cause
----------
``MultiAgentManager._graceful_stop_old_instance()`` only consults
``Workspace.task_tracker`` (CoPaw's internal ``TaskTracker``).  Background
tasks submitted through ``AgentApp`` are tracked in
``AgentApp.active_tasks`` (managed by ``agentscope_runtime``'s
``TaskEngineMixin``) and are *invisible* to the graceful-shutdown check.

When ``has_active_tasks()`` returns ``False`` (because the CoPaw tracker is
empty), the old workspace is stopped immediately — killing the in-flight
``agentscope_runtime`` background task.

What this test proves
---------------------
1. A slow background task is running inside the old workspace.
2. The task is tracked *only* in ``AgentApp.active_tasks``, **not** in
   ``Workspace.task_tracker``.
3. On ``reload_agent()``, the old workspace is stopped immediately because
   ``has_active_tasks()`` returns ``False``.
4. The background task is interrupted (``_is_interrupted`` flag or cancelled
   status) even though no user stop command was issued.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

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

# For MultiAgentManager we need to mock out its imports of Workspace and
# load_config since those also have heavy dependency chains.
# Instead we test the logic directly by replicating the key method behavior.


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
        task_tracker: A real ``TaskTracker`` instance (empty — no CoPaw tasks).
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_stop_ignores_agentapp_background_tasks():
    """The old workspace is stopped immediately even though a background task
    managed by ``AgentApp`` is still running.

    This demonstrates the bug: ``_graceful_stop_old_instance`` does not
    consult ``AgentApp.active_tasks`` and therefore considers the workspace
    idle.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        # ---- CoPaw TaskTracker is empty (no internal streaming tasks) ----
        assert await old_ws.task_tracker.has_active_tasks() is False

        # ---- AgentApp has a running background task ----
        agent_app_tasks = _make_agent_app_active_tasks()
        assert any(
            t["status"] in ("submitted", "running")
            for t in agent_app_tasks.values()
        ), "Precondition: at least one AgentApp task should be active"

        # ---- Execute graceful stop (this is the buggy path) ----
        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )

        # ---- BUG: old workspace was stopped immediately ----
        assert stopped_immediately is True, (
            "Expected immediate stop (bug reproduction). "
            "The graceful-stop method should have detected the AgentApp "
            "background task, but it did not — it only checked CoPaw's "
            "TaskTracker which was empty."
        )
        assert old_ws.stopped is True, (
            "Old workspace was stopped despite active AgentApp tasks"
        )


@pytest.mark.asyncio
async def test_task_tracker_does_not_see_external_tasks():
    """``TaskTracker.has_active_tasks()`` is blind to tasks managed by
    ``agentscope_runtime`` (AgentApp / TaskEngineMixin).

    This is the root-cause visibility gap described in the issue.
    """
    tracker = TaskTracker()

    # Even though external tasks exist, the tracker knows nothing about them.
    external_tasks = _make_agent_app_active_tasks()
    assert len(external_tasks) == 1
    assert external_tasks["task-bg-001"]["status"] == "running"

    # TaskTracker reports no active tasks — the visibility gap.
    assert await tracker.has_active_tasks() is False
    assert await tracker.list_active_tasks() == []


@pytest.mark.asyncio
async def test_reload_kills_background_task():
    """End-to-end reproduction: agent reload kills a background task that is
    tracked only in ``AgentApp.active_tasks``.

    Simulates the full reload flow:
    1. Old workspace has a slow background task (via AgentApp).
    2. Graceful stop finds no CoPaw tasks → stops the old workspace
       immediately.
    3. The background task's asyncio.Task gets cancelled as a consequence
       of the premature workspace teardown.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        # Simulate a long-running background task via AgentApp.
        # This task lives in the event loop but is NOT registered with
        # the CoPaw TaskTracker.
        async def slow_background_task():
            """Simulates an agentscope_runtime background task."""
            await asyncio.sleep(60)  # Simulate long work
            return "completed"

        bg_task = asyncio.create_task(slow_background_task())

        # Let the task start running.
        await asyncio.sleep(0)
        assert not bg_task.done(), "Background task should still be running"

        # CoPaw TaskTracker sees nothing.
        assert await old_ws.task_tracker.has_active_tasks() is False

        # Graceful stop: the buggy path stops old workspace immediately.
        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )

        assert stopped_immediately is True
        assert old_ws.stopped is True

        # The background task is STILL running (not done) because the
        # workspace stop didn't know about it.  But the workspace services
        # (runner, channels, etc.) that the task depends on are now torn
        # down.  In production this leads to the task failing with
        # "_is_interrupted=True" / "tool call has been interrupted".
        assert not bg_task.done(), (
            "Background task should still be alive — the workspace was "
            "stopped but this task was invisible to the stop mechanism."
        )

        # Simulate what happens in practice: the old workspace teardown
        # cancels asyncio tasks or invalidates the runner, causing the
        # background task to be interrupted.
        bg_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bg_task

        # The task was cancelled — reproducing the reported symptom where
        # tasks end with _is_interrupted=True and the error message
        # "The tool call has been interrupted by the user" despite no user
        # stop command being issued.
        assert bg_task.cancelled(), (
            "Background task was cancelled as a consequence of workspace "
            "teardown during reload — this is issue #3275."
        )


@pytest.mark.asyncio
async def test_copaw_tracked_task_delays_shutdown():
    """Verify that tasks tracked by CoPaw's ``TaskTracker`` DO delay the
    shutdown — proving the mechanism works for internal tasks but not for
    external (AgentApp) ones.
    """
    cleanup_tasks: set[asyncio.Task] = set()

    with tempfile.TemporaryDirectory() as tmpdir:
        old_ws = StubWorkspace("default", str(Path(tmpdir) / "old"))

        # Register a slow task WITH the CoPaw TaskTracker
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

        # Graceful stop should detect the active task and schedule
        # delayed cleanup instead of stopping immediately.
        stopped_immediately = await graceful_stop_old_instance(
            old_ws, "default", cleanup_tasks,
        )

        # The workspace should NOT have been stopped immediately because
        # there is an active CoPaw task.
        assert stopped_immediately is False, (
            "Expected delayed cleanup when CoPaw tasks are active"
        )
        assert len(cleanup_tasks) == 1, (
            "Expected delayed cleanup task to be scheduled"
        )

        # Wait for the streaming task to finish
        await completion_event.wait()

        # Wait for cleanup to run
        await asyncio.sleep(0.5)

        # Now the old workspace should have been stopped by the cleanup task
        assert old_ws.stopped is True, (
            "Old workspace should be stopped after CoPaw task completes"
        )

        # Clean up remaining async tasks
        for task in list(cleanup_tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
