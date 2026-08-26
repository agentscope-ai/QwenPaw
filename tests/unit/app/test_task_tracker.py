# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.task_tracker.TaskTracker``.

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
import pytest

from qwenpaw.app.task_tracker import REPLAY_END_EVENT, TaskTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _drain(queue: asyncio.Queue, n: int) -> list:
    """Read up to ``n`` items from ``queue`` with a small timeout."""
    items = []
    for _ in range(n):
        items.append(await asyncio.wait_for(queue.get(), timeout=1))
    return items


def _make_stream(events: list[dict]):
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


@pytest.mark.asyncio
async def test_has_active_tasks_excluding_uses_task_identity():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()
    producer_sees_other: list[bool] = []

    async def producer(_payload):
        producer_sees_other.append(
            await tracker.has_active_tasks_excluding(
                asyncio.current_task(),
            ),
        )
        started.set()
        await release.wait()
        yield {"type": "done"}

    queue, _ = await tracker.attach_or_start(
        "tracked-producer",
        None,
        producer,
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    assert producer_sees_other == [False]
    assert await tracker.has_active_tasks_excluding(
        asyncio.current_task(),
    )

    release.set()
    async for _ in tracker.stream_from_queue(queue, "tracked-producer"):
        pass


# ---------------------------------------------------------------------------
# attach_or_start: producer/consumer flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_or_start_streams_events_and_marks_completion():
    tracker = TaskTracker()
    events = [{"type": "a"}, {"type": "b"}]

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
async def test_attach_or_start_reports_completion_before_becoming_idle():
    tracker = TaskTracker()
    completions = []

    async def on_finished(run_key, finished_at):
        completions.append((run_key, finished_at))
        assert await tracker.get_status(run_key) == "running"

    queue, _ = await tracker.attach_or_start(
        "run-with-callback",
        payload=None,
        stream_fn=_make_stream([]),
        on_finished=on_finished,
    )
    assert await asyncio.wait_for(queue.get(), timeout=1) is None

    assert len(completions) == 1
    assert completions[0][0] == "run-with-callback"
    assert await tracker.get_status("run-with-callback") == "idle"


@pytest.mark.asyncio
async def test_attach_or_start_existing_run_returns_buffer_replay():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(_payload):
        yield {"type": "first"}
        started.set()
        await release.wait()
        yield {"type": "second"}

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
    assert first_b == {"type": "first"}

    # Let the producer finish.
    release.set()

    # Both queues see the remaining events and the terminator.
    rest_a = await _drain(queue_a, 3)  # first, second, SENTINEL
    rest_b = await _drain(queue_b, 2)  # second, SENTINEL

    assert rest_a == [{"type": "first"}, {"type": "second"}, None]
    assert rest_b == [{"type": "second"}, None]


@pytest.mark.asyncio
async def test_heartbeat_is_live_but_not_buffered_for_reconnect():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()
    heartbeat = {"type": "heartbeat"}
    content = {"type": "content", "text": "heartbeat"}

    async def slow_stream(_payload):
        yield heartbeat
        yield content
        started.set()
        await release.wait()

    live_queue, _ = await tracker.attach_or_start(
        "run-heartbeat",
        payload=None,
        stream_fn=slow_stream,
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert await _drain(live_queue, 2) == [heartbeat, content]

    reconnect_queue = await tracker.attach("run-heartbeat")
    assert reconnect_queue is not None
    assert await _drain(reconnect_queue, 2) == [
        content,
        REPLAY_END_EVENT,
    ]

    release.set()
    assert await asyncio.wait_for(live_queue.get(), timeout=1) is None
    assert await asyncio.wait_for(reconnect_queue.get(), timeout=1) is None


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
        yield {"type": "never"}

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
# Error path: producer exception broadcasts an error event.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_producer_exception_emits_error_event():
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

    assert err == {"error": "internal server error"}
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
        yield {"type": "done"}

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
    events = [{"type": "1"}, {"type": "2"}]

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
# wait_all_done: timeout behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_all_done_returns_true_when_idle():
    tracker = TaskTracker()

    assert await tracker.wait_all_done(timeout=0.5) is True


@pytest.mark.asyncio
async def test_wait_all_done_times_out_when_task_runs():
    tracker = TaskTracker()
    release = asyncio.Event()

    async def producer(_payload):
        await release.wait()
        yield {"type": "done"}

    queue, _ = await tracker.attach_or_start(
        "run-long",
        payload=None,
        stream_fn=producer,
    )

    try:
        assert await tracker.wait_all_done(timeout=0.2) is False
    finally:
        release.set()
        async for _ in tracker.stream_from_queue(queue, "run-long"):
            pass


@pytest.mark.asyncio
async def test_snapshot_active_tasks_filters_by_owner():
    tracker = TaskTracker()
    owner_a = object()
    owner_b = object()
    release = asyncio.Event()

    async def producer(_payload):
        await release.wait()
        yield {"type": "done"}

    queue_a, _ = await tracker.attach_or_start(
        "run-owner-a",
        None,
        producer,
        owner=owner_a,
    )
    queue_b, _ = await tracker.attach_or_start(
        "run-owner-b",
        None,
        producer,
        owner=owner_b,
    )

    try:
        snapshot = await tracker.snapshot_active_tasks(owner=owner_a)
        assert list(snapshot) == ["run-owner-a"]
    finally:
        release.set()
        async for _ in tracker.stream_from_queue(queue_a, "run-owner-a"):
            pass
        async for _ in tracker.stream_from_queue(queue_b, "run-owner-b"):
            pass


@pytest.mark.asyncio
async def test_wait_tasks_done_ignores_runs_started_after_snapshot():
    tracker = TaskTracker()
    release_old = asyncio.Event()
    release_new = asyncio.Event()

    async def old_producer(_payload):
        await release_old.wait()
        yield {"type": "old"}

    async def new_producer(_payload):
        await release_new.wait()
        yield {"type": "new"}

    old_queue, _ = await tracker.attach_or_start(
        "run-old",
        None,
        old_producer,
    )
    snapshot = await tracker.snapshot_active_tasks()
    new_queue, _ = await tracker.attach_or_start(
        "run-new",
        None,
        new_producer,
    )

    release_old.set()
    assert await tracker.wait_tasks_done(
        list(snapshot.values()),
        timeout=1,
    )
    assert await tracker.get_status("run-new") == "running"

    release_new.set()
    async for _ in tracker.stream_from_queue(old_queue, "run-old"):
        pass
    async for _ in tracker.stream_from_queue(new_queue, "run-new"):
        pass


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
        yield {"type": "done"}

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


# ---------------------------------------------------------------------------
# attach(): replay-end marker for reconnect fast-forward
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_appends_replay_end_marker_after_buffer():
    """Reconnect subscribers get the buffered events, then a
    ``replay_end`` marker, then live events. The marker lets the client
    render the replayed part instantly instead of re-animating it."""
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(_payload):
        yield {"type": "first"}
        started.set()
        await release.wait()
        yield {"type": "second"}

    queue_a, _ = await tracker.attach_or_start(
        "run-replay",
        payload=None,
        stream_fn=slow_stream,
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)

    queue_b = await tracker.attach("run-replay")
    assert queue_b is not None

    first = await asyncio.wait_for(queue_b.get(), timeout=1)
    marker = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert first == {"type": "first"}
    assert marker == REPLAY_END_EVENT

    release.set()
    rest_b = await _drain(queue_b, 2)
    assert rest_b == [{"type": "second"}, None]
    # The original (non-reconnect) subscriber never sees the marker.
    rest_a = await _drain(queue_a, 3)
    assert rest_a == [{"type": "first"}, {"type": "second"}, None]
