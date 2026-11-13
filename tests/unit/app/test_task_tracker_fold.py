# -*- coding: utf-8 -*-
"""Functional integration tests for folded TaskTracker replay."""

# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from qwenpaw.app.replay_store import ReplayStore
from qwenpaw.app.task_tracker import REPLAY_END_SSE, TaskTracker


def _content(text: str) -> str:
    """Build one mergeable text-content SSE event."""
    payload = {
        "type": "text",
        "delta": True,
        "index": 0,
        "status": "in_progress",
        "object": "content",
        "msg_id": "message-a",
        "text": text,
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _stream(events: list[str]) -> Any:
    """Return a producer that yields ``events``."""

    async def produce(_payload: Any) -> AsyncIterator[str]:
        for event in events:
            await asyncio.sleep(0)
            yield event

    return produce


def _gated_stream(
    events: list[str],
    pause_at: int,
) -> tuple[Any, asyncio.Event, asyncio.Event]:
    """Return a producer that pauses before ``pause_at``."""
    reached = asyncio.Event()
    release = asyncio.Event()

    async def produce(_payload: Any) -> AsyncIterator[str]:
        for index, event in enumerate(events):
            if index == pause_at:
                reached.set()
                await release.wait()
            await asyncio.sleep(0)
            yield event

    return produce, reached, release


async def _collect(queue: asyncio.Queue) -> list[str]:
    """Collect a subscriber queue until its terminal sentinel."""
    events: list[str] = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=5)
        if event is None:
            return events
        events.append(event)


def _fold(events: list[str]) -> list[str]:
    """Return the replay store result for ``events``."""
    store = ReplayStore()
    for event in events:
        store.append(event)
    return list(store.replay())


async def test_live_subscriber_receives_original_events() -> None:
    """Folding the replay copy does not change live broadcasting."""
    events = [_content("hello "), _content("world")]
    tracker = TaskTracker()

    queue, is_new = await tracker.attach_or_start(
        "run-live",
        payload=None,
        stream_fn=_stream(events),
    )

    assert is_new is True
    assert await _collect(queue) == events


async def test_reconnect_gets_fold_then_marker_and_live_tail() -> None:
    """A reconnect switches from folded replay to untouched live data."""
    control = 'data: {"type": "turn_usage", "tokens": 3}\n\n'
    events = [
        _content("hello "),
        control,
        _content("world"),
        _content("!"),
    ]
    tracker = TaskTracker()
    stream_fn, reached, release = _gated_stream(events, 3)

    live, is_new = await tracker.attach_or_start(
        "run-reconnect",
        payload=None,
        stream_fn=stream_fn,
    )
    assert is_new is True
    await asyncio.wait_for(reached.wait(), timeout=5)

    reconnect = await tracker.attach("run-reconnect")
    assert reconnect is not None
    release.set()

    assert await _collect(live) == events
    received = await _collect(reconnect)
    replayed = _fold(events[:3])
    assert received == [*replayed, REPLAY_END_SSE, events[-1]]
    assert REPLAY_END_SSE not in replayed


async def test_materialized_attach_snapshots_prefix_before_live_tail() -> None:
    """Future events cannot enter ahead of the materialized replay prefix."""
    response = (
        'data: {"id":"response-a","object":"response",'
        '"status":"in_progress","output":[]}\n\n'
    )
    message = (
        'data: {"id":"message-a","object":"message",'
        '"type":"message","role":"assistant",'
        '"status":"in_progress","content":[]}\n\n'
    )
    events = [response, message, _content("hello "), _content("world")]
    tracker = TaskTracker()
    stream_fn, reached, release = _gated_stream(events, 3)

    live, _ = await tracker.attach_or_start(
        "run-snapshot",
        payload=None,
        stream_fn=stream_fn,
    )
    await asyncio.wait_for(reached.wait(), timeout=5)

    attached = await tracker.attach_materialized("run-snapshot")
    assert attached is not None
    prefix, future = attached
    release.set()

    assert await _collect(live) == events
    assert len(prefix) == 1
    snapshot = json.loads(prefix[0][len("data: ") :])
    assert snapshot["output"][0]["content"][0]["text"] == "hello "
    assert await _collect(future) == [events[-1]]


async def test_error_replays_after_completion() -> None:
    """A producer failure reaches live and reconnect subscribers once."""
    first = _content("before failure")
    reached = asyncio.Event()
    release = asyncio.Event()

    async def fail(_payload: Any) -> AsyncIterator[str]:
        yield first
        reached.set()
        await release.wait()
        raise RuntimeError("boom")

    tracker = TaskTracker()
    live, _ = await tracker.attach_or_start(
        "run-error",
        payload=None,
        stream_fn=fail,
    )
    await asyncio.wait_for(reached.wait(), timeout=5)
    reconnect = await tracker.attach("run-error")
    assert reconnect is not None
    release.set()

    error = 'data: {"error": "internal server error"}\n\n'
    assert await _collect(live) == [first, error]
    assert await _collect(reconnect) == [
        first,
        REPLAY_END_SSE,
        error,
    ]
    terminal = await tracker.attach("run-error")
    assert terminal is not None
    assert await _collect(terminal) == [
        first,
        error,
        REPLAY_END_SSE,
    ]
