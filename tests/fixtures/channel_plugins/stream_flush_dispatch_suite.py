"""Base dispatch retains previews through native delivery or cancellation."""

import asyncio

import pytest

import slack_support as support
from slack_support import eventually, finish, rows, slack

runtime = support.runtime
slack_sdk = support.slack_sdk
fault_runtime = support.fault_runtime


def delay_first_update(sdk, seconds):
    """Delay only the external preview; final Slack delivery stays real."""
    boundary = sdk.site / "qwenpaw_slack_test_boundary.py"
    with boundary.open("a") as stream:
        stream.write(f"""
_flush_effect = effect
_flush_first_update = True
async def effect(kind, token=None):
    global _flush_first_update
    if kind == "chat.update" and _flush_first_update:
        _flush_first_update = False
        record("flush-preview-start", token)
        try:
            await asyncio.sleep({seconds!r})
        except asyncio.CancelledError:
            record("flush-preview-cancelled", token)
            raise
        record("flush-preview-complete", token)
    return await _flush_effect(kind, token)
""")


class Dispatch:
    """Real event schemas and Base routing, with independent response state."""

    def __init__(self, channel, ident="answer", kind="message"):
        self.channel, self.ident, self.kind = channel, ident, kind
        self.meta = {"slack_channel_id": "C123"}
        self.types, self.buffers = {}, {}
        self.tasks = []

    async def event(self, event):
        assert await self.channel._dispatch_streaming_event(
            None, "C123", event, self.meta, self.types, self.buffers
        )
        for state in self.meta.get("_stream_flush", {}).values():
            if state.get("task") is not None:
                self.tasks.append(state["task"])

    async def start(self):
        from qwenpaw.schemas import Message, RunStatus

        await self.event(
            Message(
                id=self.ident,
                object="message",
                type=self.kind,
                status=RunStatus.InProgress,
            )
        )

    async def delta(self, text, index=0):
        from qwenpaw.schemas import TextContent

        await self.event(
            TextContent(
                object="content",
                msg_id=self.ident,
                index=index,
                delta=True,
                text=text,
            )
        )

    async def end(self):
        from qwenpaw.schemas import Message, RunStatus

        await self.event(
            Message(
                id=self.ident,
                object="message",
                type=self.kind,
                status=RunStatus.Completed,
            )
        )

    def assert_drained(self):
        assert self.meta.get("_stream_flush", {}) == {}
        assert all(task.done() for task in self.tasks)
        assert self.buffers == {}
        assert self.types == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["next_delta", "completion", "split"])
async def test_six_second_native_preview_keeps_full_final_and_segment_order(
    runtime, slack_sdk, transition
):
    delay_first_update(slack_sdk, 6.0)
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    stream = Dispatch(rt.channel)
    await stream.start()
    await stream.delta("first")
    await eventually(lambda: rows(slack_sdk.work, "flush-preview-start"))
    if transition == "next_delta":
        await asyncio.sleep(5.1)
        await stream.delta(" final")
    elif transition == "split":
        await stream.delta("second", index=1)
    await stream.end()
    assert not stream.meta.get("_reply_unknown")
    assert rows(slack_sdk.work, "flush-preview-cancelled") == []
    assert len(rows(slack_sdk.work, "flush-preview-complete")) == 1
    updates = rows(slack_sdk.work, "chat.update")
    if transition == "split":
        posts = rows(slack_sdk.work, "post-result")
        assert len(posts) == 2
        assert [
            (v["arguments"]["ts"], v["arguments"]["text"]) for v in updates
        ] == [
            (posts[0]["ts"], "first"),
            (posts[0]["ts"], "first"),
            (posts[1]["ts"], "second"),
            (posts[1]["ts"], "second"),
        ]
    else:
        assert [v["arguments"]["text"] for v in updates] == [
            "first",
            "first final" if transition == "next_delta" else "first",
        ]
    stream.assert_drained()
    await finish(rt, stream.meta["response_handle"])


@pytest.mark.asyncio
@pytest.mark.parametrize("join_after_expiry", [False, True])
async def test_native_short_budget_fences_unknown_without_replay(
    runtime, slack_sdk, join_after_expiry
):
    import time

    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    delay_first_update(slack_sdk, 0.8)
    rt = await slack(
        runtime,
        slack_sdk,
        streaming_enabled=True,
        runtime_settings={"send_timeouts": {"slack": 0.3}},
    )
    stream = Dispatch(rt.channel)
    await stream.start()
    await stream.delta("first")
    await eventually(lambda: rows(slack_sdk.work, "flush-preview-start"))
    task = stream.tasks[-1]
    if join_after_expiry:
        await eventually(task.done)
    else:
        await asyncio.sleep(0.24)
    started = time.monotonic()
    with pytest.raises(ChannelDeliveryError) as caught:
        await stream.end()
    assert caught.value.state == "unknown"
    assert time.monotonic() - started < 0.2
    assert stream.meta["_reply_unknown"] is True
    assert task.done()
    assert len(rows(slack_sdk.work, "flush-preview-cancelled")) == 1
    with pytest.raises(ChannelDeliveryError) as replay:
        await rt.channel.send("C123", "must not replay", stream.meta)
    assert replay.value.state == "unknown"
    assert [
        v["arguments"]["text"] for v in rows(slack_sdk.work, "chat.update")
    ] == ["first"]
    assert len(rows(slack_sdk.work, "post-result")) == 1
    assert stream.meta.get("_stream_flush", {}) == {}


@pytest.mark.asyncio
async def test_manager_stop_retains_live_preview_until_ack_then_retries(
    runtime, slack_sdk, monkeypatch
):
    import time
    import psutil
    import qwenpaw.plugins.custody as custody
    from qwenpaw.plugins.registry import PluginRegistry

    delay_first_update(slack_sdk, 0.5)
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    stream = Dispatch(rt.channel)
    await stream.start()
    await stream.delta("first")
    await eventually(lambda: rows(slack_sdk.work, "flush-preview-start"))
    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.05)
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager._CHANNEL_DRAIN_TIMEOUT", 0.05
    )
    pid = rt.process.health_snapshot()["pid"]
    started = time.monotonic()
    receipt = await rt.manager.stop_one("slack")
    assert time.monotonic() - started < 0.3
    assert not receipt.stopped
    assert await rt.manager.get_channel("slack") is rt.channel
    assert PluginRegistry().runtime_owners.leases("slack")
    assert psutil.pid_exists(pid)
    assert rows(slack_sdk.work, "flush-preview-cancelled") == []
    assert not stream.meta.get("_reply_unknown")
    await stream.end()
    assert [
        v["arguments"]["text"] for v in rows(slack_sdk.work, "chat.update")
    ] == ["first", "first"]
    stream.assert_drained()
    receipt = await rt.manager.stop_one("slack")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert await rt.manager.get_channel("slack") is None
    assert not psutil.pid_exists(pid)
    assert not PluginRegistry().runtime_owners.leases("slack")


@pytest.mark.asyncio
async def test_failed_agent_iterator_cancels_native_preview_before_error_send(
    runtime, slack_sdk, monkeypatch
):
    from qwenpaw.schemas import Message, RunStatus, TextContent

    delay_first_update(slack_sdk, 2.0)
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    requests = []
    closed = asyncio.Event()

    async def process(request):
        requests.append(request)
        try:
            yield Message(
                id="broken", object="message", status=RunStatus.InProgress
            )
            yield TextContent(
                object="content", msg_id="broken", delta=True, text="first"
            )
            await eventually(
                lambda: rows(slack_sdk.work, "flush-preview-start")
            )
            raise RuntimeError("controlled agent failure")
        finally:
            closed.set()

    monkeypatch.setattr(rt.channel, "_process", process)
    with pytest.raises(RuntimeError, match="controlled agent failure"):
        async for _event in rt.channel._stream_with_tracker(
            {
                "sender_id": "U456",
                "session_id": "C123",
                "user_id": "C123",
                "content_parts": [{"type": "text", "text": "question"}],
                "meta": {"slack_channel_id": "C123"},
            }
        ):
            pass
    assert closed.is_set()
    assert requests[0].channel_meta["_reply_unknown"] is True
    assert len(rows(slack_sdk.work, "flush-preview-cancelled")) == 1
    assert len(rows(slack_sdk.work, "chat.update")) == 1
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    assert requests[0].channel_meta.get("_stream_flush", {}) == {}
