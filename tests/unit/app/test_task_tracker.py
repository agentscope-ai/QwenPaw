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

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument
import asyncio
import json

import pytest

from qwenpaw.app.task_tracker import RunInput, RunOutcome, RunStarted, TaskTracker
from qwenpaw.runtime.reply_cycle import InputStateEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _drain(queue: asyncio.Queue, n: int) -> list:
    """Read up to ``n`` items from ``queue`` with a small timeout."""
    items = []
    while len(items) < n:
        item = await asyncio.wait_for(queue.get(), timeout=1)
        if item is None or isinstance(item, str):
            items.append(item)
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
@pytest.mark.parametrize(
    "payload,status",
    [
        (
            {
                "object": "response",
                "status": "failed",
                "error": {"message": "unavailable"},
            },
            "failed",
        ),
        ({"object": "message", "type": "tool_call", "status": "failed"}, "completed"),
    ],
)
async def test_outcome_distinguishes_run_failure_from_tool_failure(payload, status):
    tracker = TaskTracker()
    queue, _ = await tracker.attach_or_start(
        "chat", None, _make_stream([f"data: {json.dumps(payload)}\n\n"])
    )
    events = [event async for event in tracker.stream_events_from_queue(queue, "chat")]
    assert isinstance(events[-1], RunOutcome)
    assert events[-1].status == status


@pytest.mark.asyncio
async def test_stop_before_producer_starts_still_publishes_outcome():
    tracker = TaskTracker()
    queue, _ = await tracker.attach_or_start("chat", None, _make_stream([]))
    await tracker.request_stop("chat")

    async def collect():
        return [item async for item in tracker.stream_events_from_queue(queue, "chat")]

    events = await asyncio.wait_for(collect(), 1)
    assert isinstance(events[0], RunStarted)
    assert len(events) == 2 and events[-1].status == "cancelled"
    assert not tracker._runs


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
        yield "data: done\n\n"

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
    events = ["data: a\n\n", "data: b\n\n"]

    queue, is_new = await tracker.attach_or_start(
        "run-1",
        payload=None,
        stream_fn=_make_stream(events),
    )

    assert is_new is True

    # Drain the two real events plus the SENTINEL terminator.
    assert isinstance(await queue.get(), RunStarted)
    a = await asyncio.wait_for(queue.get(), timeout=1)
    b = await asyncio.wait_for(queue.get(), timeout=1)
    outcome = await asyncio.wait_for(queue.get(), timeout=1)
    sentinel = await asyncio.wait_for(queue.get(), timeout=1)

    assert [a, b] == events
    assert isinstance(outcome, RunOutcome)
    assert outcome.status == "completed"
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
async def test_attach_or_start_publishes_initial_events_before_producer():
    tracker = TaskTracker()
    initial = "data: user\n\n"
    produced = "data: assistant\n\n"

    queue, is_new = await tracker.attach_or_start(
        "run-initial",
        payload=None,
        stream_fn=_make_stream([produced]),
        initial_events=[initial],
    )

    assert is_new is True
    assert await _drain(queue, 3) == [initial, produced, None]


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
    assert isinstance(await queue_b.get(), RunStarted)
    first_b = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert first_b == "data: first\n\n"

    # Let the producer finish.
    release.set()

    # Both queues see the remaining events and the terminator.
    rest_a = await _drain(queue_a, 3)  # first, second, SENTINEL
    rest_b = await _drain(queue_b, 3)  # replay boundary, second, SENTINEL

    assert rest_a == ["data: first\n\n", "data: second\n\n", None]
    assert rest_b[0] == 'data: {"type": "replay_end"}\n\n'
    assert rest_b[1:] == ["data: second\n\n", None]


@pytest.mark.asyncio
async def test_attach_live_does_not_replay_prior_output():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()

    async def stream(_payload):
        yield "data: old\n\n"
        started.set()
        await release.wait()
        yield "data: new\n\n"

    original, _ = await tracker.attach_or_start("live", None, stream)
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)
    live = await tracker.attach_live("live")
    assert live is not None and live.empty()

    release.set()
    assert await _drain(live, 2) == ["data: new\n\n", None]
    assert await _drain(original, 3) == [
        "data: old\n\n",
        "data: new\n\n",
        None,
    ]


@pytest.mark.asyncio
async def test_named_live_subscriber_is_unique_per_run():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()

    async def stream(_payload):
        started.set()
        await release.wait()
        yield "data: final\n\n"

    original, _ = await tracker.attach_or_start("named", None, stream)
    await asyncio.wait_for(started.wait(), timeout=1)

    first = await tracker.attach_live_once("named", "voice-projection")
    second = await tracker.attach_live_once("named", "voice-projection")

    assert first is not None
    assert second is None

    await tracker.detach_subscriber("named", first)
    replacement = await tracker.attach_live_once(
        "named",
        "voice-projection",
    )
    assert replacement is not None

    release.set()
    assert await _drain(replacement, 2) == ["data: final\n\n", None]
    assert await _drain(original, 2) == ["data: final\n\n", None]


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


@pytest.mark.asyncio
async def test_submit_or_start_is_atomic_and_idempotent():
    tracker = TaskTracker()
    started = asyncio.Event()
    release = asyncio.Event()
    captured_payload = None

    async def producer(payload):
        nonlocal captured_payload
        captured_payload = payload
        started.set()
        await release.wait()
        yield "data: done\n\n"

    payload = {"meta": {"request_context": {}}}
    initial_sse = 'data: {"id":"client-initial","role":"user"}\n\n'

    async def reserve_order():
        return 12

    queue, status, run_id = await tracker.submit_or_start(
        "steer-run",
        payload,
        producer,
        RunInput(("initial",), "initial"),
        accepted_sse=initial_sse,
        reserve_timeline_order=reserve_order,
    )
    assert status == "started"
    assert run_id
    await asyncio.wait_for(started.wait(), timeout=1)

    accepted_sse = 'data: {"id":"client-evt-1","role":"user"}\n\n'
    live_queue, status, accepted_run_id = await tracker.submit_or_start(
        "steer-run",
        payload,
        producer,
        RunInput(("one",), "evt-1"),
        accepted_sse=accepted_sse,
    )
    assert status == "accepted"
    assert accepted_run_id == run_id
    duplicate_queue, status, duplicate_run_id = await tracker.submit_or_start(
        "steer-run",
        payload,
        producer,
        RunInput(("ignored",), "evt-1"),
    )
    assert status == "duplicate"
    assert duplicate_run_id == run_id
    mailbox = captured_payload["meta"]["request_context"]["_run_input_mailbox"]
    reply_cycle = captured_payload["meta"]["request_context"]["_reply_cycle_context"]
    assert reply_cycle.run_id == run_id
    assert reply_cycle.snapshot.group_id == "initial"
    assert (await reply_cycle.start_occurrence()).timeline_order == 12
    assert [item.content_parts for item in mailbox.drain_after_reply()] == [
        ("one",),
    ]
    assert await _drain(queue, 2) == [initial_sse, accepted_sse]

    await tracker.detach_subscriber("steer-run", live_queue)
    await tracker.detach_subscriber("steer-run", duplicate_queue)
    release.set()
    async for _ in tracker.stream_from_queue(queue, "steer-run"):
        pass


@pytest.mark.asyncio
async def test_attach_or_start_waits_for_finishing_run_then_starts_next():
    tracker = TaskTracker()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    payload = {"meta": {"request_context": {}}}

    async def first_stream(_payload):
        first_started.set()
        await release_first.wait()
        yield "data: first\n\n"

    first_queue, first_is_new = await tracker.attach_or_start(
        "same-chat",
        payload,
        first_stream,
    )
    assert first_is_new is True
    await asyncio.wait_for(first_started.wait(), timeout=1)
    payload["meta"]["request_context"]["_run_input_mailbox"].close()

    async def second_stream(_payload):
        yield "data: second\n\n"

    next_start = asyncio.create_task(
        tracker.attach_or_start(
            "same-chat",
            {"meta": {"request_context": {}}},
            second_stream,
        ),
    )
    await asyncio.sleep(0)
    assert not next_start.done()

    release_first.set()
    second_queue, second_is_new = await asyncio.wait_for(
        next_start,
        timeout=1,
    )
    assert second_is_new is True
    assert await _drain(first_queue, 2) == ["data: first\n\n", None]
    assert await _drain(second_queue, 2) == ["data: second\n\n", None]


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

    assert isinstance(await queue.get(), RunStarted)
    err = await asyncio.wait_for(queue.get(), timeout=1)
    outcome = await asyncio.wait_for(queue.get(), timeout=1)
    sentinel = await asyncio.wait_for(queue.get(), timeout=1)

    assert err.startswith("data: ")
    payload = json.loads(err[len("data: ") :].rstrip("\n"))
    assert payload == {"error": "internal server error"}
    assert outcome.status == "failed"
    assert outcome.error == "kaboom"
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

    collected = [item async for item in tracker.stream_from_queue(queue, "run-stream")]

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
        yield "data: done\n\n"

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
        yield "data: done\n\n"

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
        yield "data: old\n\n"

    async def new_producer(_payload):
        await release_new.wait()
        yield "data: new\n\n"

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
        yield "data: first\n\n"
        started.set()
        await release.wait()
        yield "data: second\n\n"

    queue_a, _ = await tracker.attach_or_start(
        "run-replay",
        payload=None,
        stream_fn=slow_stream,
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0)

    queue_b = await tracker.attach("run-replay")
    assert queue_b is not None
    assert isinstance(await queue_b.get(), RunStarted)

    first = await asyncio.wait_for(queue_b.get(), timeout=1)
    marker = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert first == "data: first\n\n"
    assert marker.startswith("data: ")
    assert json.loads(marker[len("data: ") :].strip()) == {
        "type": "replay_end",
    }

    release.set()
    rest_b = await _drain(queue_b, 2)
    assert rest_b == ["data: second\n\n", None]
    # The original (non-reconnect) subscriber never sees the marker.
    rest_a = await _drain(queue_a, 3)
    assert rest_a == ["data: first\n\n", "data: second\n\n", None]


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", ["saved", "failed"])
async def test_reconnect_after_retirement_preserves_storage_result(saved):
    tracker = TaskTracker()
    payload = {"meta": {"request_context": {}}}

    async def stream(data):
        data["meta"]["request_context"]["_session_save_result"].status = saved
        yield "data: output\n\n"

    await tracker.attach_or_start("chat", payload, stream)
    assert await tracker.wait_all_done(timeout=2)
    queue = await tracker.attach("chat", include_finished=True)
    events = [
        item async for item in tracker.stream_from_queue(queue, "chat", lifecycle=True)
    ]
    event = json.loads(events[0][len("data: ") :])
    assert event["type"] == "run_sealed"
    assert event["persistence"] == saved
    assert await tracker.get_status("chat") == "idle"
