# -*- coding: utf-8 -*-
"""Regression tests for run cleanup in ``TaskTracker._producer``.

``_producer`` clears its ``_runs`` entry (and pushes the end-of-stream
sentinel) at the end of a ``finally`` block, after awaiting the ``on_finished``
completion callback. Two failure modes matter, both verified here against
observable behaviour rather than internal state:

1. The callback hangs (it persists a marker under ``ChatManager``'s shared
   lock). The producer task then never completes, so the run stays
   registered *and* not-done: every status reader reports "running", which
   blocks workspace reload and makes inbound messages get dropped with
   HTTP 409. The callback must therefore be time-bounded.
2. The producer is cancelled while the callback is in flight.
   ``CancelledError`` is a ``BaseException``, so it escapes any
   ``except Exception`` guard; cleanup must still run or the subscriber
   stream never terminates.

Waits are event-based (``asyncio.wait_for`` on a real event) rather than
fixed sleeps so the tests cannot pass by accident on a slow machine.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app import task_tracker as task_tracker_mod
from qwenpaw.app.task_tracker import TaskTracker


async def _one_event_stream(_payload):
    yield "data: one\n\n"


def _drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    """Poll *predicate* until true or *timeout* elapses."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.001)
    return predicate()


# ---------------------------------------------------------------------------
# A hung completion callback must not pin the run as "running".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hung_completion_callback_does_not_block_new_messages(
    monkeypatch,
):
    """A callback that never returns must not wedge the run.

    This is the reported failure: status stuck at "running", reload
    blocked, inbound messages rejected. Asserted through the same public
    calls the router uses.
    """
    monkeypatch.setattr(
        task_tracker_mod,
        "ON_FINISHED_TIMEOUT",
        0.05,
        raising=False,
    )
    tracker = TaskTracker()
    entered = asyncio.Event()

    async def hanging_callback(_run_key, _finished_at):
        entered.set()
        await asyncio.Event().wait()  # never returns

    queue, is_new = await tracker.attach_or_start(
        "run-hung-callback",
        payload=None,
        stream_fn=_one_event_stream,
        on_finished=hanging_callback,
    )
    assert is_new is True
    await asyncio.wait_for(entered.wait(), timeout=1)

    # Once the callback times out, cleanup must have completed.
    assert await _wait_until(
        lambda: "run-hung-callback" not in tracker._runs,
    ), "run entry survived a hung completion callback"

    assert await tracker.get_status("run-hung-callback") == "idle"
    assert await tracker.has_active_tasks() is False
    assert await tracker.list_active_tasks() == []
    # Reload path consults this; a stuck True blocks instance replacement.
    assert await tracker.has_active_tasks_excluding(None) is False

    # A new inbound message must be accepted (is_new_run False == HTTP 409).
    _q2, is_new_again = await tracker.attach_or_start(
        "run-hung-callback",
        payload=None,
        stream_fn=_one_event_stream,
    )
    assert is_new_again is True

    # The original subscriber stream must have been terminated.
    seen = _drain(queue)
    assert "data: one\n\n" in seen
    assert seen[-1] is None, "stream must end with the sentinel"


@pytest.mark.asyncio
async def test_completion_callback_timeout_is_logged_not_raised(
    monkeypatch,
    caplog,
):
    """Timeout is a warning; it must not surface as a run error."""
    monkeypatch.setattr(
        task_tracker_mod,
        "ON_FINISHED_TIMEOUT",
        0.05,
        raising=False,
    )
    tracker = TaskTracker()
    entered = asyncio.Event()

    async def hanging_callback(_run_key, _finished_at):
        entered.set()
        await asyncio.Event().wait()

    with caplog.at_level("WARNING"):
        await tracker.attach_or_start(
            "run-timeout-logged",
            payload=None,
            stream_fn=_one_event_stream,
            on_finished=hanging_callback,
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert await _wait_until(
            lambda: "run-timeout-logged" not in tracker._runs,
        )

    assert "completion callback timed out" in caplog.text
    # The run finished normally from the subscriber's point of view.
    assert await tracker.get_status("run-timeout-logged") == "idle"


@pytest.mark.asyncio
async def test_failing_completion_callback_still_clears_the_run():
    """A raising callback must not leak the entry (pre-existing guard)."""
    tracker = TaskTracker()
    entered = asyncio.Event()

    async def raising_callback(_run_key, _finished_at):
        entered.set()
        raise RuntimeError("callback exploded")

    await tracker.attach_or_start(
        "run-failing-callback",
        payload=None,
        stream_fn=_one_event_stream,
        on_finished=raising_callback,
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    assert await _wait_until(
        lambda: "run-failing-callback" not in tracker._runs,
    ), "run entry survived a failing completion callback"
    assert await tracker.has_active_tasks() is False


# ---------------------------------------------------------------------------
# Cancellation while the callback is in flight.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_during_callback_still_clears_the_run():
    """CancelledError escapes ``except Exception``; cleanup must run anyway."""
    tracker = TaskTracker()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_callback(_run_key, _finished_at):
        entered.set()
        await release.wait()

    queue, _is_new = await tracker.attach_or_start(
        "run-cancelled",
        payload=None,
        stream_fn=_one_event_stream,
        on_finished=slow_callback,
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    tracker._runs["run-cancelled"].task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tracker._runs["run-cancelled"].task

    assert await _wait_until(
        lambda: "run-cancelled" not in tracker._runs,
    ), "run entry survived cancellation during the callback"
    assert await tracker.get_status("run-cancelled") == "idle"

    seen = _drain(queue)
    assert "data: one\n\n" in seen
    assert seen[-1] is None, "cancelled run must still terminate the stream"


@pytest.mark.asyncio
async def test_request_stop_with_a_slow_callback_does_not_wedge_the_run(
    monkeypatch,
):
    """The reported stop path: stop while the callback is still running.

    ``request_stop`` cancels the producer and awaits it. With a bounded
    callback this always terminates and leaves no active run.
    """
    monkeypatch.setattr(
        task_tracker_mod,
        "ON_FINISHED_TIMEOUT",
        0.05,
        raising=False,
    )
    tracker = TaskTracker()
    entered = asyncio.Event()

    async def slow_callback(_run_key, _finished_at):
        entered.set()
        await asyncio.sleep(5)

    await tracker.attach_or_start(
        "run-stop-slow",
        payload=None,
        stream_fn=_one_event_stream,
        on_finished=slow_callback,
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    assert await tracker.request_stop("run-stop-slow", reason="test") is True

    assert await _wait_until(
        lambda: "run-stop-slow" not in tracker._runs,
    ), "request_stop left the run registered"
    assert await tracker.has_active_tasks() is False
    assert await tracker.get_status("run-stop-slow") == "idle"


# ---------------------------------------------------------------------------
# A TimeoutError raised by the callback itself must not be reported as a hang.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_raising_timeout_error_is_not_logged_as_a_hang(
    monkeypatch,
    caplog,
):
    """Our bound firing vs the callback raising TimeoutError are distinct."""
    monkeypatch.setattr(
        task_tracker_mod,
        "ON_FINISHED_TIMEOUT",
        5.0,
        raising=False,
    )
    tracker = TaskTracker()
    entered = asyncio.Event()

    async def raising_timeout(_run_key, _finished_at):
        entered.set()
        raise TimeoutError("repo layer timed out")

    with caplog.at_level("WARNING"):
        await tracker.attach_or_start(
            "run-callback-timeout-error",
            payload=None,
            stream_fn=_one_event_stream,
            on_finished=raising_timeout,
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert await _wait_until(
            lambda: "run-callback-timeout-error" not in tracker._runs,
        )

    assert (
        "timed out after" not in caplog.text
    ), "a callback-raised TimeoutError must not be reported as our hang"
    assert "completion callback failed" in caplog.text
    assert await tracker.get_status("run-callback-timeout-error") == "idle"
