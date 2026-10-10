# -*- coding: utf-8 -*-
"""Unit tests for EventLoopWatchdog.

Verifies:
1. Lifecycle: start, tick, stop cleanly without thread leakage.
2. Stall detection: detects event loop lag exceeding threshold.
3. Live stack capture: captures the exact frame blocking the event loop.
4. Culprit attribution: identifies plugin files/frames causing the stall.
5. Recovery: records stall recovery when the loop unblocks.
"""

import asyncio
import time
import pytest

from qwenpaw.utils.event_loop_watchdog import EventLoopWatchdog


@pytest.mark.asyncio
async def test_watchdog_lifecycle():
    """Test start and stop cleanly."""
    loop = asyncio.get_running_loop()
    watchdog = EventLoopWatchdog(
        loop=loop,
        stall_threshold=0.2,
        check_interval=0.05,
    )
    watchdog.start()
    assert watchdog.is_running()

    # Let it run a few cycles
    await asyncio.sleep(0.15)
    stats = watchdog.get_stats()
    assert stats["stall_count"] == 0
    assert not stats["is_stalled"]

    watchdog.stop()
    assert not watchdog.is_running()


@pytest.mark.asyncio
async def test_watchdog_detects_stall_and_captures_stack():
    """Test that a synchronous blocking call on the loop triggers detection
    and stack capture.
    """
    loop = asyncio.get_running_loop()
    watchdog = EventLoopWatchdog(
        loop=loop,
        stall_threshold=0.15,
        check_interval=0.05,
    )
    watchdog.start()

    try:
        # Define a named function to appear in the captured stack trace
        def simulated_blocking_operation():
            time.sleep(0.35)

        # Execute synchronously on loop (simulating bad plugin behavior)
        simulated_blocking_operation()

        # Allow watchdog thread to record recovery
        await asyncio.sleep(0.1)

        stats = watchdog.get_stats()
        assert stats["stall_count"] >= 1
        assert stats["max_lag"] >= 0.25
        assert stats["last_stall_stack"] is not None
        assert "simulated_blocking_operation" in stats["last_stall_stack"]
        assert "time.sleep" in stats["last_stall_stack"]
    finally:
        watchdog.stop()


@pytest.mark.asyncio
async def test_watchdog_plugin_culprit_attribution():
    """Test identifying plugin path in the captured stack trace."""
    loop = asyncio.get_running_loop()
    watchdog = EventLoopWatchdog(
        loop=loop,
        stall_threshold=0.15,
        check_interval=0.05,
    )

    # Create a code object with a simulated plugin filename
    plugin_code = compile(
        "import time\n"
        "def run_plugin_task():\n"
        "    time.sleep(0.35)\n"
        "run_plugin_task()",
        "/custom/path/to/plugins/my-demo-plugin/entry.py",
        "exec",
    )

    watchdog.start()
    try:
        # Execute the compiled code on the loop
        exec(plugin_code, {})

        await asyncio.sleep(0.1)

        stats = watchdog.get_stats()
        assert stats["stall_count"] >= 1
        assert stats["last_culprit"] is not None
        assert "my-demo-plugin" in stats["last_culprit"]
    finally:
        watchdog.stop()
