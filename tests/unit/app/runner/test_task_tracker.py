# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.runner.task_tracker.TaskTracker``.

Covers:
- idle/running status before/after a task
- external task registration round-trip and idempotency
- attach() to non-existent / completed / live runs
- attach_or_start() reuses an in-flight run vs. starting a new one
- request_stop() cancels and reports running state
- detach_subscriber() removes queues and is idempotent
- stream_from_queue() yields events and detaches on consumer exit
- wait_all_done() returns True when idle, False on timeout
- global status counters update via run lifecycle
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import json

import pytest

from qwenpaw.app.runner.task_tracker import TaskTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _drain(queue: asyncio.Queue, n: int) -> list:
    """Read up to ``n`` items from ``queue`` with a small timeout."""
    items = []
    for _ in range(n):
        items.append(await asyncio.wait_for(queue.get(), timeout=1))
    return items


def _make_stream(events: list[str]):
    async def stream(_payload):
        for ev in events:
            await asyncio.sleep(0)  # cooperate
            yield ev

    return stream


# ---------------------------------------------------------------------------
# get_status / has_active_tasks / list_active_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_idle_for_unknown_run_key():
    tracker = TaskTracker()

    assert await tracker.get_status("missing") == "idle"
    assert await tracker.has_active_tasks() is False
    assert await tracker.list_active_tasks() == []


@pytest.mark.asyncio
async def test_attach_returns_none_for_unknown_run_key():
    tracker = TaskTracker()

    assert await tracker.attach("missing") is None


# ---------------------------------------------------------------------------
# attach_or_start: producer/consumer flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_or_start_streams_events_and_marks_completion():
    tracker = TaskTracker()
    events = ["data: a\n\n", "data: b\n\n"]

    queue, is_new = await tracker.attach_or_start(
        "run-1",
        payload=None,
        stream_fn=_make_stream(events),
    )

    assert is_new is True

    # Drain the two real events plus the SENTINEL terminator.
    a = await asyncio.wait_for(queue.get(), timeout=1)
    b = await asyncio.wait_for(queue.get(), timeout=1)
    sentinel = await asyncio.wait_for(queue.get(), timeout=1)

    assert [a, b] == events
    assert sentinel is None

    # After completion the tracker cleans up the run.
    assert await tracker.get_status("run-1") == "idle"
    assert "run-1" not in tracker._runs


@pytest.mark.asyncio
async def test_attach_or_start_existing_run_returns_buffer_replay():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(_payload):
        yield "data: first\n\n"
        started.set()
        await release.wait()
        yield "data: second\n\n"

    queue_a, new_a = await tracker.attach_or_start(
        "run-2",
        payload=None,
        stream_fn=slow_stream,
    )
    assert new_a is True

    # Wait until the producer has yielded the first event so the buffer
    # contains something to replay.
    await asyncio.wait_for(started.wait(), timeout=1)
    # Yield once more so the broadcast under the lock completes before
    # the second attach_or_start tries to read the buffer.
    await asyncio.sleep(0)

    queue_b, new_b = await tracker.attach_or_start(
        "run-2",
        payload=None,
        stream_fn=_make_stream([]),  # must NOT be invoked
    )
    assert new_b is False

    # queue_b should be pre-filled with the buffered first event.
    first_b = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert first_b == "data: first\n\n"

    # Let the producer finish.
    release.set()

    # Both queues see the remaining events and the terminator.
    rest_a = await _drain(queue_a, 3)  # first, second, SENTINEL
    rest_b = await _drain(queue_b, 2)  # second, SENTINEL

    assert rest_a == ["data: first\n\n", "data: second\n\n", None]
    assert rest_b == ["data: second\n\n", None]


# ---------------------------------------------------------------------------
# request_stop: cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_stop_cancels_live_run():
    tracker = TaskTracker()
    started = asyncio.Event()

    async def long_stream(_payload):
        started.set()
        await asyncio.sleep(60)
        yield "never"

    await tracker.attach_or_start(
        "run-cancel",
        payload=None,
        stream_fn=long_stream,
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    assert await tracker.get_status("run-cancel") == "running"

    stopped = await tracker.request_stop("run-cancel")
    assert stopped is True

    # Give the task loop time to process cancellation and cleanup.
    await asyncio.sleep(0.05)

    assert await tracker.get_status("run-cancel") == "idle"


@pytest.mark.asyncio
async def test_request_stop_returns_false_when_no_run():
    tracker = TaskTracker()

    assert await tracker.request_stop("missing") is False


# ---------------------------------------------------------------------------
# Error path: producer exception broadcasts an error SSE.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_producer_exception_emits_error_sse():
    tracker = TaskTracker()

    async def boom(_payload):
        # Make the function an async generator without yielding anything,
        # so attach_or_start treats it like a real stream that errors out.
        if False:  # pylint: disable=using-constant-test
            yield
        raise RuntimeError("kaboom")

    queue, _ = await tracker.attach_or_start(
        "run-error",
        payload=None,
        stream_fn=boom,
    )

    err = await asyncio.wait_for(queue.get(), timeout=1)
    sentinel = await asyncio.wait_for(queue.get(), timeout=1)

    assert err.startswith("data: ")
    payload = json.loads(err[len("data: ") :].rstrip("\n"))
    assert payload == {"error": "internal server error"}
    assert sentinel is None


# ---------------------------------------------------------------------------
# detach_subscriber: idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detach_subscriber_is_idempotent():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated(_payload):
        started.set()
        await release.wait()
        yield "data: done\n\n"

    queue, _ = await tracker.attach_or_start(
        "run-detach",
        payload=None,
        stream_fn=gated,
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    # Detach twice — second call is a no-op.
    await tracker.detach_subscriber("run-detach", queue)
    await tracker.detach_subscriber("run-detach", queue)
    # Detaching a never-registered run also no-ops.
    await tracker.detach_subscriber("nope", queue)

    release.set()
    # Drain to allow producer cleanup.
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# stream_from_queue: consumer detaches on exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_from_queue_yields_until_sentinel_and_detaches():
    tracker = TaskTracker()
    events = ["data: 1\n\n", "data: 2\n\n"]

    queue, _ = await tracker.attach_or_start(
        "run-stream",
        payload=None,
        stream_fn=_make_stream(events),
    )

    collected = [
        item async for item in tracker.stream_from_queue(queue, "run-stream")
    ]

    assert collected == events
    # After streaming, run is cleaned up, so detach should be a no-op.
    assert await tracker.get_status("run-stream") == "idle"


# ---------------------------------------------------------------------------
# External task lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_task_register_and_unregister_round_trip():
    tracker = TaskTracker()

    await tracker.register_external_task("ext-1")

    assert await tracker.get_status("ext-1") == "running"
    assert await tracker.has_active_tasks() is True
    assert "ext-1" in await tracker.list_active_tasks()

    summary = await tracker.get_global_status()
    assert summary["status"] == "running"
    assert summary["running_task_count"] == 1
    assert summary["last_run_at"] is not None

    await tracker.unregister_external_task("ext-1")

    assert await tracker.get_status("ext-1") == "idle"
    assert await tracker.has_active_tasks() is False
    after = await tracker.get_global_status()
    assert after["status"] == "idle"
    assert after["running_task_count"] == 0
    assert after["last_finish_at"] is not None


@pytest.mark.asyncio
async def test_external_task_register_is_idempotent_for_live_run():
    tracker = TaskTracker()

    await tracker.register_external_task("ext-dup")
    first_state = tracker._runs["ext-dup"]
    await tracker.register_external_task("ext-dup")  # second call is no-op

    assert tracker._runs["ext-dup"] is first_state

    await tracker.unregister_external_task("ext-dup")


@pytest.mark.asyncio
async def test_unregister_external_task_unknown_is_safe():
    tracker = TaskTracker()

    # Should not raise.
    await tracker.unregister_external_task("never-registered")


@pytest.mark.asyncio
async def test_unregister_external_task_drains_subscriber_queues():
    tracker = TaskTracker()
    await tracker.register_external_task("ext-sub")

    # Manually attach a queue (external tasks bypass attach_or_start).
    q: asyncio.Queue = asyncio.Queue()
    async with tracker._lock:
        tracker._runs["ext-sub"].queues.append(q)

    await tracker.unregister_external_task("ext-sub")

    sentinel = await asyncio.wait_for(q.get(), timeout=1)
    assert sentinel is None


# ---------------------------------------------------------------------------
# wait_all_done: timeout behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_all_done_returns_true_when_idle():
    tracker = TaskTracker()

    assert await tracker.wait_all_done(timeout=0.5) is True


@pytest.mark.asyncio
async def test_wait_all_done_times_out_when_task_runs():
    tracker = TaskTracker()
    await tracker.register_external_task("ext-long")

    try:
        assert await tracker.wait_all_done(timeout=0.2) is False
    finally:
        await tracker.unregister_external_task("ext-long")


# ---------------------------------------------------------------------------
# Concurrent attach / start safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_attach_or_start_only_one_producer():
    tracker = TaskTracker()
    invocations = 0
    release = asyncio.Event()

    async def producer(_payload):
        nonlocal invocations
        invocations += 1
        await release.wait()
        yield "data: done\n\n"

    queues = await asyncio.gather(
        tracker.attach_or_start("run-concurrent", None, producer),
        tracker.attach_or_start("run-concurrent", None, producer),
        tracker.attach_or_start("run-concurrent", None, producer),
    )

    new_flags = [is_new for _, is_new in queues]
    assert new_flags.count(True) == 1
    assert invocations == 1

    release.set()
    # Let the producer finish so the test does not leak background tasks.
    for q, _ in queues:
        while True:
            item = await asyncio.wait_for(q.get(), timeout=1)
            if item is None:
                break
