# -*- coding: utf-8 -*-
"""Real worker-process lifecycle contracts for browser execution."""

from __future__ import annotations

# pylint: disable=protected-access

import asyncio
import os
import time

from fastapi import FastAPI

from qwenpaw.app._app import _start_browser_runtime, _stop_browser_runtime
from qwenpaw.browser.execution.kernel import KernelRuntime
from qwenpaw.browser.execution.subprocess_plane import SubprocessPlane
from qwenpaw.browser.execution.wire import ExecRequest


def _request(
    request_id: str,
    session_id: str,
    code: str,
) -> ExecRequest:
    return ExecRequest(
        request_id=request_id,
        code=code,
        owner_workspace_id="workspace",
        owner_session_id=session_id,
    )


async def test_worker_is_reused_then_reclaimed() -> None:
    plane = SubprocessPlane()
    request = _request("reuse", "session", "import os\nreturn os.getpid()")
    key = "workspace/session"
    try:
        first = await plane.run(key, request)
        second = await plane.run(key, request)

        assert first.value != str(os.getpid())
        assert second.value == first.value
        await plane.discard_idle_workers(0.0)
        assert key not in plane._workers
    finally:
        await plane.discard_all_workers()


async def test_sibling_sessions_run_without_serializing() -> None:
    plane = SubprocessPlane()
    runtime = KernelRuntime(plane=plane)
    slow = _request(
        "slow",
        "slow",
        "import asyncio\nawait asyncio.sleep(1.0)\nreturn 'slow'",
    )
    fast = _request("fast", "fast", "return 'fast'")
    try:
        slow_task = asyncio.create_task(runtime.run(slow))
        await asyncio.sleep(0.15)
        started = time.monotonic()
        fast_result = await runtime.run(fast)

        assert fast_result.value == "fast"
        assert not slow_task.done()
        assert time.monotonic() - started < 0.75
        assert (await slow_task).value == "slow"
    finally:
        await plane.discard_all_workers()


async def test_timeout_reclaims_only_the_affected_worker() -> None:
    plane = SubprocessPlane(exec_timeout_seconds=5.0)
    runtime = KernelRuntime(plane=plane)
    sibling_key = "workspace/sibling"
    try:
        assert (
            await runtime.run(_request("first", "sibling", "return 1"))
        ).error is None
        sibling_pid = plane._workers[sibling_key].proc.pid
        timed_out = await runtime.run(
            _request(
                "timeout",
                "timeout",
                "import asyncio\nawait asyncio.sleep(6.0)\nreturn 'late'",
            ),
        )

        assert timed_out.error is not None
        assert timed_out.error["category"] == "TIMEOUT"
        assert "workspace/timeout" not in plane._workers
        assert plane._workers[sibling_key].proc.pid == sibling_pid
    finally:
        await plane.discard_all_workers()


async def test_runtime_shutdown_reclaims_real_workers() -> None:
    plane = SubprocessPlane()
    runtime = KernelRuntime(plane=plane)
    app = FastAPI()
    try:
        assert (
            await runtime.run(_request("shutdown", "session", "return 'ok'"))
        ).error is None
        _start_browser_runtime(app, runtime, interval=60.0)

        await _stop_browser_runtime(app)

        assert not plane._workers
        assert app.state.browser_watchdog.cancelled()
    finally:
        await plane.discard_all_workers()
