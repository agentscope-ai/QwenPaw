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
    """Sibling sessions must run in parallel, not queue behind one lock.

    Instead of timing a single fast request against a wall-clock budget
    (flaky: worker-process spawn cost varies by runner), measure the
    total span of two overlapping tasks:

    - a long task sleeps 3.0 s in session A, started first;
    - a short task sleeps 2.0 s in session B, started while A is still
      running.

    If the sessions run in parallel the span is ~3.0 s (the longer of
    the two); if they are wrongly serialized it is ~5.0 s (3 + 2).  A
    bound of 4.5 s leaves ~1.5 s of headroom for runner jitter on the
    parallel side while the serialized case still overshoots it by
    ~0.5 s, so normal runner jitter cannot flip the verdict.  Both
    workers are warmed up first so subprocess spawn cost stays out of
    the timed span.
    """
    plane = SubprocessPlane()
    runtime = KernelRuntime(plane=plane)
    long_request = _request(
        "long",
        "sibling-a",
        "import asyncio\nawait asyncio.sleep(3.0)\nreturn 'long'",
    )
    short_request = _request(
        "short",
        "sibling-b",
        "import asyncio\nawait asyncio.sleep(2.0)\nreturn 'short'",
    )
    try:
        # Warm up both workers so spawn cost is outside the timed span.
        await runtime.run(_request("warm-a", "sibling-a", "return 'ok'"))
        await runtime.run(_request("warm-b", "sibling-b", "return 'ok'"))

        started = time.monotonic()
        long_task = asyncio.create_task(runtime.run(long_request))
        await asyncio.sleep(0.15)
        short_result = await runtime.run(short_request)

        assert short_result.value == "short"
        # The long task is still running when the short one returns —
        # direct proof the sessions did not queue behind each other.
        assert not long_task.done()
        long_result = await long_task
        elapsed = time.monotonic() - started

        assert long_result.value == "long"
        # Parallel ≈ 3.0 s; a serialized implementation would need ≈ 5.0 s.
        assert (
            elapsed < 4.5
        ), f"sibling sessions appear serialized: took {elapsed:.2f}s"
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
