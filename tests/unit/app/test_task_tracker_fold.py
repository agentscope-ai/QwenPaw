# -*- coding: utf-8 -*-
"""Reconnect behaviour of ``TaskTracker`` on top of the folded replay store.

``test_task_tracker.py`` locks the tracker's contract with non-JSON payloads,
which pass through a fold untouched and so cannot see it. These tests drive
the same tracker with a real console-shaped stream and assert the two halves
of the design separately:

*   the live broadcast is byte for byte the stream the producer yielded
    (contract C1, criterion 3) — folding touches the replay copy only;
*   what a reconnecting subscriber gets — the fold, the ``replay_end``
    marker, then the live tail — reduces to the same conversation as
    watching the run from the start (criterion 2, at the tracker level);
*   the marker never enters the replay copy (contract C5) and the error SSE
    a failing producer synthesizes is retained verbatim (criterion 5);
*   replay state hangs off ``_RunState``, never off the tracker, because a
    workspace reload reuses one tracker for many runs (analysis R7).
"""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List, Tuple

from qwenpaw.app.replay_store import ReplayStore
from qwenpaw.app.task_tracker import REPLAY_END_SSE, TaskTracker
from tests.unit.app import replay_corpus as corpus
from tests.unit.app import replay_oracle as oracle


def _fold(lines: List[str]) -> List[str]:
    """Return the replay copy ``lines`` folds to."""
    store = ReplayStore()
    for sse in lines:
        store.append(sse)
    return list(store.replay())


def _summary(lines: List[str]) -> Any:
    """Return the state a client renders after consuming ``lines``."""
    return oracle.summarize(oracle.reduce(lines))


def _make_stream(events: List[str]) -> Any:
    """Return a ``stream_fn`` that yields ``events`` and nothing else."""

    async def stream(_payload: Any) -> AsyncIterator[str]:
        for sse in events:
            await asyncio.sleep(0)
            yield sse

    return stream


def _make_gated_stream(
    events: List[str],
    pause_at: int,
) -> Tuple[Any, asyncio.Event, asyncio.Event]:
    """Return a ``stream_fn`` that blocks before yielding ``pause_at``.

    The gate sits between events, so once the caller observes ``reached``
    the replay copy holds exactly ``events[:pause_at]``: the producer
    appends and broadcasts each event before asking for the next one.
    """
    reached = asyncio.Event()
    release = asyncio.Event()

    async def stream(_payload: Any) -> AsyncIterator[str]:
        for index, sse in enumerate(events):
            if index == pause_at:
                reached.set()
                await release.wait()
            await asyncio.sleep(0)
            yield sse

    return stream, reached, release


def _make_failing_stream(
    events: List[str],
) -> Tuple[Any, asyncio.Event, asyncio.Event]:
    """Return a ``stream_fn`` that yields ``events`` and then raises."""
    reached = asyncio.Event()
    release = asyncio.Event()

    async def stream(_payload: Any) -> AsyncIterator[str]:
        for sse in events:
            await asyncio.sleep(0)
            yield sse
        reached.set()
        await release.wait()
        raise RuntimeError("producer blew up")

    return stream, reached, release


async def _collect(queue: asyncio.Queue) -> List[str]:
    """Return everything ``queue`` yields, excluding the terminal sentinel."""
    out: List[str] = []
    while True:
        item = await asyncio.wait_for(queue.get(), timeout=5)
        if item is None:
            return out
        out.append(item)


async def _take(queue: asyncio.Queue, count: int) -> List[str]:
    """Return the next ``count`` items of ``queue``, sentinel included."""
    out: List[str] = []
    for _ in range(count):
        out.append(await asyncio.wait_for(queue.get(), timeout=5))
    return out


async def test_live_broadcast_is_byte_identical_to_the_stream() -> None:
    """A subscriber from the start sees every event, unchanged (C1)."""
    tracker = TaskTracker()
    stream = await corpus.synthetic_stream(2, corpus.spaced)
    queue, is_new = await tracker.attach_or_start(
        "run-broadcast",
        payload=None,
        stream_fn=_make_stream(stream),
    )
    assert is_new is True
    assert await _collect(queue) == stream


async def test_reconnect_replays_the_fold_then_the_live_tail() -> None:
    """The reconnect path renders what the live path renders."""
    tracker = TaskTracker()
    stream = await corpus.synthetic_stream(3, corpus.spaced)
    cut = len(stream) // 2
    stream_fn, reached, release = _make_gated_stream(stream, cut)

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

    assert await _collect(live) == stream
    received = await _collect(reconnect)
    assert received.count(REPLAY_END_SSE) == 1
    boundary = received.index(REPLAY_END_SSE)
    replayed, tail = received[:boundary], received[boundary + 1 :]

    # The replay is genuinely folded, the tail is the untouched rest of the
    # run, and together they cover the whole stream exactly once.
    assert len(replayed) < cut
    assert replayed == _fold(stream[:cut])
    assert tail == stream[cut:]

    # Criterion 2 at the tracker level. The marker maps to a heartbeat the
    # builder skips, so dropping it here is the only difference between this
    # stream and the live one.
    assert _summary(replayed + tail) == _summary(stream)


async def test_replay_end_marker_never_enters_the_replay_store() -> None:
    """A second reconnect never replays the marker the first one was sent."""
    tracker = TaskTracker()
    stream = await corpus.synthetic_stream(2, corpus.spaced)
    cut = len(stream) // 2
    stream_fn, reached, release = _make_gated_stream(stream, cut)

    _, is_new = await tracker.attach_or_start(
        "run-marker",
        payload=None,
        stream_fn=stream_fn,
    )
    assert is_new is True
    await asyncio.wait_for(reached.wait(), timeout=5)

    first = await tracker.attach("run-marker")
    assert first is not None
    second = await tracker.attach("run-marker")
    assert second is not None

    # C4 stays as it is: ``attach`` sends the marker right after the fold.
    folded = _fold(stream[:cut])
    prefix = await _take(second, len(folded) + 1)
    assert prefix == [*folded, REPLAY_END_SSE]
    release.set()

    await _collect(first)
    tail = await _collect(second)
    assert tail == stream[cut:]
    assert REPLAY_END_SSE not in tail


async def test_error_sse_is_broadcast_and_replayed_verbatim() -> None:
    """A failing producer's error frame reaches both copies unchanged."""
    tracker = TaskTracker()
    stream = await corpus.synthetic_stream(1, corpus.spaced)
    stream_fn, reached, release = _make_failing_stream(stream)

    live, is_new = await tracker.attach_or_start(
        "run-error",
        payload=None,
        stream_fn=stream_fn,
    )
    assert is_new is True
    await asyncio.wait_for(reached.wait(), timeout=5)

    # Keep a handle on the run. The producer pops it from the tracker in its
    # ``finally``, but the replay copy it wrote is what a reconnect would
    # have been served, so that is the thing worth asserting on.
    state = tracker._runs["run-error"]
    reconnect = await tracker.attach("run-error")
    assert reconnect is not None
    release.set()

    assert await _collect(live) == [*stream, corpus.ERROR_SSE]
    received = await _collect(reconnect)
    assert received.count(corpus.ERROR_SSE) == 1
    assert received[-1] == corpus.ERROR_SSE

    retained = list(state.replay.replay())
    assert retained[-1] == corpus.ERROR_SSE
    # The error frame carries no ``object`` field, so the classifier cannot
    # route it and C7 keeps it byte for byte.
    assert _summary(retained) == _summary([*stream, corpus.ERROR_SSE])
    assert not tracker._runs, "the run must be popped once it finishes"


async def test_replay_state_lives_on_the_run_not_the_tracker() -> None:
    """Two runs on one tracker never see each other's replay copy (R7)."""
    tracker = TaskTracker()
    first_stream = await corpus.synthetic_stream(
        1,
        corpus.spaced,
        session_id="session-one",
    )
    second_stream = await corpus.partial_stream(corpus.spaced)
    first_fn, first_hit, first_go = _make_gated_stream(first_stream, 4)
    second_fn, second_hit, second_go = _make_gated_stream(second_stream, 4)

    first_live, _ = await tracker.attach_or_start(
        "run-one",
        payload=None,
        stream_fn=first_fn,
    )
    second_live, _ = await tracker.attach_or_start(
        "run-two",
        payload=None,
        stream_fn=second_fn,
    )
    await asyncio.wait_for(first_hit.wait(), timeout=5)
    await asyncio.wait_for(second_hit.wait(), timeout=5)
    first_replay = tracker._runs["run-one"].replay
    second_replay = tracker._runs["run-two"].replay
    assert first_replay is not second_replay

    view = await tracker.attach("run-one")
    assert view is not None
    folded = _fold(first_stream[:4])
    assert await _take(view, len(folded) + 1) == [*folded, REPLAY_END_SSE]

    first_go.set()
    second_go.set()
    assert await _collect(first_live) == first_stream
    assert await _collect(second_live) == second_stream
    assert not tracker._runs, "the run must be popped once it finishes"
