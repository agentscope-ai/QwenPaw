"""A generic SDK channel exercises Base event budgets and cleanup ownership."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.schemas import Message, RunStatus, TextContent
from stream_flush_dispatch_suite import Dispatch


class SDKChannel(BaseChannel):
    """Minimal SDK hooks, with an observable external send and cleanup gate."""

    channel = "sdk-test"

    def __init__(self, process=None, *, slow_cleanup=False):
        super().__init__(process, streaming_enabled=True)
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelling = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        self.slow_cleanup = slow_cleanup
        self.effects = []
        self.tasks = []
        self.meta = None
        self._STREAM_FLUSH_TIMEOUT_S = 1.0

    async def on_streaming_start(self, request, to, event, meta, kind, **kw):
        self.meta = meta

    async def on_streaming_delta(self, request, to, event, meta, kind, **kw):
        self.tasks.append(asyncio.current_task())
        self.started.set()
        try:
            await self.release.wait()
            self.effects.append((kind, kw["accumulated_text"]))
        except asyncio.CancelledError:
            self.cancelling.set()
            if self.slow_cleanup:
                await self.cleanup_release.wait()
            raise
        finally:
            self.cleaned.set()

    async def on_streaming_end(self, request, to, event, meta, kind, **kw):
        self.effects.append(("final:" + kind, kw["accumulated_text"]))


def message(status):
    return Message(id="answer", object="message", status=status)


def delta():
    return TextContent(
        object="content", msg_id="answer", delta=True, text="answer"
    )


def request():
    return SimpleNamespace(
        session_id="", input=[], user_id="C123", channel_meta={}
    )


async def consume(channel):
    return [event async for event in channel._stream_with_tracker(request())]


@pytest.mark.asyncio
async def test_generic_hook_budget_starts_once_before_near_deadline_join():
    channel = SDKChannel()
    channel._STREAM_FLUSH_TIMEOUT_S = 0.2
    stream = Dispatch(channel)
    await stream.start()
    await stream.delta("first")
    await channel.started.wait()
    await asyncio.sleep(0.15)
    join_started = time.monotonic()
    with pytest.raises(TimeoutError):
        await stream.end()
    assert time.monotonic() - join_started < 0.12
    assert channel.cancelling.is_set()
    assert channel.cleaned.is_set()
    assert channel.effects == []
    assert all(task.done() for task in channel.tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["normal", "close", "cancel"])
async def test_full_event_iterator_cleans_unfinished_preview(exit_mode):
    blocked = asyncio.Event()
    iterator_closed = asyncio.Event()

    async def process(_request):
        try:
            yield message(RunStatus.InProgress)
            yield delta()
            await channel.started.wait()
            if exit_mode == "close":
                yield TextContent(object="content", text="")
            if exit_mode == "cancel":
                await blocked.wait()
        finally:
            iterator_closed.set()

    channel = SDKChannel(process)
    iterator = channel._stream_with_tracker(request())
    if exit_mode == "close":
        await anext(iterator)
        await anext(iterator)
        # The SSE is yielded before its dispatch; resume to start the send.
        await anext(iterator)
        await channel.started.wait()
        await iterator.aclose()
    else:
        task = asyncio.create_task(consume(channel))
        await channel.started.wait()
        if exit_mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
    assert iterator_closed.is_set()
    assert channel.cancelling.is_set()
    assert channel.cleaned.is_set()
    assert all(task.done() for task in channel.tasks)
    assert channel.meta.get("_stream_flush", {}) == {}
    assert channel.effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["completion", "split"])
async def test_caller_cancellation_during_join_propagates_without_final(
    transition,
):
    channel = SDKChannel(slow_cleanup=True)
    stream = Dispatch(channel)
    await stream.start()
    await stream.delta("first")
    await channel.started.wait()
    join = asyncio.create_task(
        stream.end()
        if transition == "completion"
        else stream.delta("second", index=1)
    )
    await asyncio.sleep(0)
    join.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await join
        assert channel.effects == []
        assert any(
            state.get("task") is channel.tasks[0]
            for state in stream.meta.get("_stream_flush", {}).values()
        )
    finally:
        channel.cleanup_release.set()
        channel.release.set()
        await asyncio.gather(*channel.tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_slow_cancellation_cleanup_keeps_stop_unready_until_settled(
    monkeypatch,
):
    import qwenpaw.plugins.custody as custody

    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.05)
    blocked = asyncio.Event()

    async def process(_request):
        yield message(RunStatus.InProgress)
        yield delta()
        await blocked.wait()

    channel = SDKChannel(process, slow_cleanup=True)
    consumer = asyncio.create_task(consume(channel))
    await channel.started.wait()
    consumer.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await channel.cancelling.wait()
        assert not channel.cleaned.is_set()
        assert (
            channel.meta["_stream_flush"]["message"]["task"]
            is channel.tasks[0]
        )
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await channel.prepare_stop()
        assert time.monotonic() - started < 0.2
        assert not channel.cleaned.is_set()
    finally:
        channel.cleanup_release.set()
        await asyncio.gather(*channel.tasks, return_exceptions=True)
    assert channel.cleaned.is_set()
    assert await channel.prepare_stop() is False


@pytest.mark.asyncio
async def test_pending_previews_isolate_response_and_message_type():
    channel = SDKChannel()
    streams = [
        Dispatch(channel, ident=ident, kind=kind)
        for ident in ("response-A", "response-B")
        for kind in ("message", "reasoning")
    ]
    # Each response shares metadata across its two stream types.
    streams[1].meta = streams[0].meta
    streams[3].meta = streams[2].meta
    for stream, text in zip(streams, ("A", "think-A", "B", "think-B")):
        await stream.start()
        await stream.delta(text)
    await asyncio.sleep(0)
    assert len(channel.tasks) == 4
    assert len(set(channel.tasks)) == 4
    for stream in streams:
        await stream.delta(" final")
    assert len(channel.tasks) == 4
    channel.release.set()
    for stream in streams:
        await stream.end()
    for stream in streams:
        stream.assert_drained()
    assert sorted(channel.effects) == sorted(
        [
            ("message", "A"),
            ("reasoning", "think-A"),
            ("message", "B"),
            ("reasoning", "think-B"),
            ("final:message", "A final"),
            ("final:reasoning", "think-A final"),
            ("final:message", "B final"),
            ("final:reasoning", "think-B final"),
        ]
    )


@pytest.mark.asyncio
async def test_generic_deadline_bounds_cancellation_resistant_join(
    monkeypatch,
):
    import qwenpaw.plugins.custody as custody

    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.05)
    channel = SDKChannel(slow_cleanup=True)
    channel._STREAM_FLUSH_TIMEOUT_S = 0.05
    stream = Dispatch(channel)
    await stream.start()
    await stream.delta("first")
    await channel.started.wait()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            await stream.end()
        assert time.monotonic() - started < 0.2
        assert channel.cancelling.is_set()
        assert not channel.cleaned.is_set()
        assert (
            stream.meta["_stream_flush"]["message"]["task"] is channel.tasks[0]
        )
        assert channel.effects == []
        with pytest.raises(TimeoutError):
            await channel.prepare_stop()
        assert not channel.cleaned.is_set()
    finally:
        channel.cleanup_release.set()
        await asyncio.gather(*channel.tasks, return_exceptions=True)
    assert channel.cleaned.is_set()
    assert await channel.prepare_stop() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["cancel", "close"])
async def test_explicit_abort_does_not_recancel_cleanup_at_send_deadline(
    monkeypatch, exit_mode
):
    import qwenpaw.plugins.custody as custody

    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.02)
    blocked = asyncio.Event()

    async def process(_request):
        yield message(RunStatus.InProgress)
        yield delta()
        await channel.started.wait()
        if exit_mode == "close":
            yield TextContent(object="content", text="")
        await blocked.wait()

    channel = SDKChannel(process, slow_cleanup=True)
    channel._STREAM_FLUSH_TIMEOUT_S = 0.08
    try:
        if exit_mode == "cancel":
            consumer = asyncio.create_task(consume(channel))
            await channel.started.wait()
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
        else:
            iterator = channel._stream_with_tracker(request())
            await anext(iterator)
            await anext(iterator)
            await anext(iterator)
            await iterator.aclose()
        await channel.cancelling.wait()
        # Cross the original business deadline while cleanup still owns work.
        await asyncio.sleep(0.1)
        task = channel.tasks[0]
        assert not task.done()
        assert task.cancelling() == 1
        assert not channel.cleaned.is_set()
        assert channel.meta["_stream_flush"]["message"]["task"] is task
        with pytest.raises(TimeoutError):
            await channel.prepare_stop()
        assert not channel.cleaned.is_set()
        assert channel.effects == []
    finally:
        channel.cleanup_release.set()
        await asyncio.gather(*channel.tasks, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        channel.tasks[0].result()
    assert channel.cleaned.is_set()
    assert await channel.prepare_stop() is False


@pytest.mark.asyncio
async def test_external_cancel_after_hook_consumes_budget_cancel_keeps_reason(
    monkeypatch,
):
    channel = SDKChannel()
    channel._STREAM_FLUSH_TIMEOUT_S = 0.05
    handled_timeout = asyncio.Event()
    blocked = asyncio.Event()

    async def hook(request, to, event, meta, kind, **kw):
        task = asyncio.current_task()
        channel.tasks.append(task)
        try:
            await blocked.wait()
        except asyncio.CancelledError:
            task.uncancel()
            handled_timeout.set()
            try:
                await blocked.wait()
            finally:
                channel.cleaned.set()

    monkeypatch.setattr(channel, "on_streaming_delta", hook)
    stream = Dispatch(channel)
    await stream.start()
    await stream.delta("first")
    await handled_timeout.wait()
    task = channel.tasks[0]
    assert not task.done()
    assert task.cancelling() == 0
    assert stream.meta["_stream_flush"]["message"]["task"] is task
    join = asyncio.create_task(stream.end())
    await asyncio.sleep(0)
    task.cancel("external cleanup cancellation")
    with pytest.raises(asyncio.CancelledError, match="external cleanup"):
        await join
    assert task.done() and task.cancelled()
    assert channel.cleaned.is_set()
    assert channel.effects == []
    assert stream.meta.get("_stream_flush", {}) == {}
    assert await channel.prepare_stop() is False
