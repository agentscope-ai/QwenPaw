# -*- coding: utf-8 -*-
"""Outer watchdog for real plugin I/O, startup and cleanup in tests.

This bounds hangs, not performance. Keep deliberate product deadlines and
negative checks (work must still be blocked) separate from this budget.
"""

import threading
import time

WAIT_TIMEOUT = 15.0


def wait_for_thread_progress(predicate):
    """Wait in a worker for observable progress without assuming disk speed."""
    deadline = time.monotonic() + WAIT_TIMEOUT
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(
                "Event loop made no progress during worker I/O",
            )
        time.sleep(0.005)


def assert_loop_progress(loop):
    """A blocked synchronous callback must still let the host loop run."""
    progressed = threading.Event()
    loop.call_soon_threadsafe(progressed.set)
    assert progressed.wait(
        WAIT_TIMEOUT,
    ), "Synchronous work blocked the event loop"
