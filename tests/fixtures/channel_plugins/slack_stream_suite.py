"""Slack stream fidelity, response ownership, concurrency and unknown
receipts."""

import asyncio
import json

import pytest

from slack_suite import forbid_host_sdk
from slack_support import (
    eventually,
    fault_runtime,
    finish,
    identity,
    route,
    rows,
    runtime,
    send,
    set_mode,
    slack,
    slack_sdk,
)
from discord_stream_suite import stream


async def stream_route(rt):
    return await route(rt, "slack:ch:C123", {"slack_channel_id": "C123"})


@pytest.mark.asyncio
async def test_host_stream_exact_reasoning_and_text_prefixes(
    runtime, slack_sdk
):
    rt = await slack(
        runtime, slack_sdk, streaming_enabled=True, bot_prefix="[SlackBot] "
    )
    meta = {"slack_channel_id": "C123", "bot_prefix": "[META] "}
    for kind in ("reasoning", "message"):
        await rt.channel.on_streaming_start(
            None, "slack:ch:C123", None, meta, kind
        )
        await rt.channel.on_streaming_delta(
            None, "slack:ch:C123", None, meta, kind, "**one**"
        )
        await rt.channel.on_streaming_end(
            None, "slack:ch:C123", None, meta, kind, "**final**"
        )
    posts = rows(slack_sdk.work, "chat.postMessage")
    assert [row["arguments"]["text"] for row in posts] == [
        "💭 ⏳ ...",
        "⏳ ...",
    ]
    edits = rows(slack_sdk.work, "chat.update")
    assert [row["arguments"]["text"] for row in edits] == [
        "💭 **one**",
        "💭 *final*",
        "**one**",
        "*final*",
    ]
    assert edits[0]["arguments"]["ts"] != edits[2]["arguments"]["ts"]
    await finish(rt, meta["response_handle"])
    assert len(rows(slack_sdk.work, "chat.update")) == 4


@pytest.mark.asyncio
async def test_safe_fallback_and_hidden_thinking(runtime, slack_sdk):
    rt = await slack(
        runtime,
        slack_sdk,
        streaming_enabled=True,
        bot_prefix="[SlackBot] ",
        show_thinking=False,
    )
    meta = {"slack_channel_id": "C123"}
    await rt.channel.on_streaming_start(None, "C123", None, meta, "reasoning")
    await rt.channel.on_streaming_delta(
        None, "C123", None, meta, "reasoning", "private thinking"
    )
    assert rows(slack_sdk.work, "chat.postMessage") == []
    assert rows(slack_sdk.work, "chat.update") == []
    await rt.channel.on_streaming_end(
        None, "C123", None, {}, "message", "Fallback text"
    )
    assert (
        rows(slack_sdk.work, "chat.postMessage")[-1]["arguments"]["text"]
        == "[SlackBot] \nFallback text"
    )
    await rt.channel.on_streaming_delta(
        None, "C123", None, {}, "message", "no placeholder"
    )
    assert rows(slack_sdk.work, "chat.update") == []
    await rt.channel.on_streaming_end(None, "C123", None, {}, "message", "")
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1


@pytest.mark.asyncio
async def test_missing_stream_channel_does_not_send_placeholder(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    meta = {}
    await rt.channel.on_streaming_start(None, "C123", None, meta, "message")
    assert rows(slack_sdk.work, "chat.postMessage") == []


@pytest.mark.asyncio
async def test_delta_throttle_is_per_owned_message_and_final_is_unconditional(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    first, second = await stream_route(rt), await stream_route(rt)
    for handle, name in ((first, "first"), (second, "second")):
        await stream(rt, handle, "start", delivery_id=name, text="...")
    await stream(
        rt,
        first,
        "delta",
        delivery_id="first-1",
        target="first",
        text="one",
        sequence=1,
    )
    await stream(
        rt,
        first,
        "delta",
        delivery_id="first-2",
        target="first",
        text="two",
        sequence=2,
    )
    assert len(rows(slack_sdk.work, "chat.update")) == 1
    await stream(
        rt,
        second,
        "delta",
        delivery_id="second-1",
        target="second",
        text="other",
        sequence=1,
    )
    assert len(rows(slack_sdk.work, "chat.update")) == 2
    await stream(
        rt,
        first,
        "end",
        delivery_id="first-end",
        target="first",
        text="final",
        sequence=3,
    )
    assert len(rows(slack_sdk.work, "chat.update")) == 3
    assert (
        rows(slack_sdk.work, "chat.update")[-1]["arguments"]["text"] == "final"
    )


@pytest.mark.asyncio
async def test_delta_tail_and_confirmed_delete_before_long_chunk_final(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    handle = await stream_route(rt)
    assert (
        await stream(rt, handle, "start", delivery_id="start", text="...")
    )["state"] == "acknowledged"
    text = "a" * 30000 + "END"
    assert (
        await stream(
            rt,
            handle,
            "delta",
            delivery_id="delta",
            target="start",
            text=text,
            sequence=1,
        )
    )["state"] == "acknowledged"
    assert (
        rows(slack_sdk.work, "chat.update")[-1]["arguments"]["text"]
        == "..." + text[-29996:]
    )
    assert (
        await stream(
            rt,
            handle,
            "end",
            delivery_id="end",
            target="start",
            text=text,
            sequence=2,
        )
    )["state"] == "acknowledged"
    effects = [
        row
        for row in rows(slack_sdk.work)
        if row["kind"] in {"chat.postMessage", "chat.delete"}
    ]
    assert [row["kind"] for row in effects] == [
        "chat.postMessage",
        "chat.delete",
        "chat.postMessage",
        "chat.postMessage",
    ]
    assert "".join(row["arguments"]["text"] for row in effects[2:]) == text
    assert all(len(row["arguments"]["text"]) <= 30000 for row in effects[2:])


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", ["chat.update", "chat.delete"])
@pytest.mark.parametrize("fault", ["unknown", "server", "cancel"])
async def test_unknown_final_edit_or_delete_never_replays_or_sends_fallback(
    runtime, slack_sdk, effect, fault
):
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    handle = await stream_route(rt)
    await stream(rt, handle, "start", delivery_id="start", text="...")
    set_mode(slack_sdk.work, effect + "-" + fault)
    text = "a" * 30100 if effect == "chat.delete" else "Final text"
    for delivery, sequence in (("end", 1), ("end", 1), ("different-end", 2)):
        if (
            fault == "cancel"
            and delivery == "end"
            and sequence == 1
            and not rows(slack_sdk.work, effect)
        ):
            from qwenpaw.plugins.execution.errors import RpcError

            with pytest.raises(RpcError, match="request cancelled") as caught:
                await stream(
                    rt,
                    handle,
                    "end",
                    delivery_id=delivery,
                    target="start",
                    text=text,
                    sequence=sequence,
                )
            assert caught.value.code == -32603
        else:
            result = await stream(
                rt,
                handle,
                "end",
                delivery_id=delivery,
                target="start",
                text=text,
                sequence=sequence,
            )
            assert result["state"] == "unknown"
    assert len(rows(slack_sdk.work, effect)) == 1
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    set_mode(slack_sdk.work, "")
    with pytest.raises(Exception):
        await finish(rt, handle)
    assert len(rows(slack_sdk.work, effect)) == 1


@pytest.mark.asyncio
async def test_unknown_post_partial_chunks_no_retry(runtime, slack_sdk):
    rt = await slack(runtime, slack_sdk)
    handle = await route(rt, "C123")
    set_mode(slack_sdk.work, "chat.postMessage-unknown")
    for _ in range(2):
        result = await send(
            rt,
            handle,
            delivery_id="lost-post",
            parts=[{"type": "text", "text": "one accepted remote message"}],
        )
        assert result["state"] == "unknown"
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    assert "unknown" in "".join(
        path.read_text()
        for path in rt.ws.workspace_dir.rglob("channel_state/*.json")
    )
    set_mode(slack_sdk.work, "")
    second = await route(rt, "C123")
    set_mode(slack_sdk.work, "post-second-server")
    result = await send(
        rt,
        second,
        delivery_id="partial",
        parts=[{"type": "text", "text": "a" * 30100}],
    )
    assert result["state"] == "unknown"
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 3
    assert (
        await send(
            rt,
            second,
            delivery_id="partial",
            parts=[{"type": "text", "text": "a" * 30100}],
        )
    )["state"] == "unknown"
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["send", "parts"])
async def test_public_cancel_same_meta_retains_unknown_no_replay_after_restart(
    runtime, slack_sdk, entry
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
        receipt_path,
    )
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await slack(runtime, slack_sdk)
    meta = {}
    parts = [{"type": "text", "text": "one remote accepted effect"}]

    async def public_send(channel):
        if entry == "send":
            return await channel.send("C123", parts[0]["text"], meta)
        return await channel.send_content_parts("C123", parts, meta)

    set_mode(slack_sdk.work, "chat.postMessage-cancel")
    with pytest.raises(RpcError, match="request cancelled") as first:
        await public_send(rt.channel)
    assert first.value.code == -32603
    assert first.value.data["reason_code"] == "REQUEST_CANCELLED"
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    custody = (meta.get("response_handle"), dict(meta["_pending_delivery"]))
    store = ResponseReceiptStore(receipt_path(rt.ws.workspace_dir, "slack"))
    archive_key = receipt_key("slack.shared.responses", custody[0])
    original = store.get(archive_key)
    if original is None:
        live = json.loads(rt.channel._state_path().read_text())
        original = next(
            row
            for row in live["slack.shared.responses"]["value"]
            if row["response_handle"] == custody[0]
        )
    original_unknown = next(
        ref
        for ref in original["resource_refs"]
        if ref["kind"] == "slack.attempt"
        and ref["resource_id"] == custody[1]["delivery_id"]
    )
    assert original_unknown["attributes"]["state"] == "unknown"
    assert len(original_unknown["attributes"]["fingerprint"]) == 64
    set_mode(slack_sdk.work, "")
    try:
        await public_send(rt.channel)
    except ChannelDeliveryError as caught:
        assert caught.state == "unknown"
    else:
        raise AssertionError(
            "same-meta retry replayed Slack post: "
            + str(len(rows(slack_sdk.work, "chat.postMessage")))
        )
    assert meta["_reply_unknown"] is True
    assert (meta["response_handle"], meta["_pending_delivery"]) == custody
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    await rt.loader.lifecycle.set_enabled("slack", False)
    await rt.loader.lifecycle.set_enabled("slack", True)
    current = await rt.manager.get_channel("slack")
    with pytest.raises(ChannelDeliveryError) as caught:
        await public_send(current)
    assert caught.value.state == "unknown"
    assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
    assert (meta["response_handle"], meta["_pending_delivery"]) == custody
    persisted = json.loads(current._state_path().read_text())
    snapshots = persisted["slack.shared.responses"]["value"]
    assert all(row["response_handle"] != custody[0] for row in snapshots)
    snapshot = store.get(archive_key)
    assert snapshot["response_handle"] == custody[0]
    assert snapshot["kind"] == "terminal"
    assert snapshot["cleanup_state"] == "complete"
    assert original_unknown in snapshot["resource_refs"]


@pytest.mark.asyncio
async def test_response_finish_and_cancel_only_own_resource(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, streaming_enabled=True)
    first, second = await stream_route(rt), await stream_route(rt)
    for handle, name in ((first, "first"), (second, "second")):
        await stream(rt, handle, "start", delivery_id=name, text="...")
        await stream(
            rt,
            handle,
            "delta",
            delivery_id=name + "-delta",
            target=name,
            text=name,
            sequence=1,
        )
    timestamps = [row["ts"] for row in rows(slack_sdk.work, "post-result")]
    assert len(timestamps) == 2 and timestamps[0] != timestamps[1]
    await finish(rt, first, "cancelled")
    assert (
        rows(slack_sdk.work, "chat.update")[-1]["arguments"]["ts"]
        == timestamps[0]
    )
    assert (
        rows(slack_sdk.work, "chat.update")[-1]["arguments"]["text"] == "first"
    )
    before = len(rows(slack_sdk.work, "chat.update"))
    await finish(rt, first, "cancelled")
    assert len(rows(slack_sdk.work, "chat.update")) == before
    await stream(
        rt,
        second,
        "end",
        delivery_id="second-end",
        target="second",
        text="second final",
        sequence=2,
    )
    assert (
        rows(slack_sdk.work, "chat.update")[-1]["arguments"]["ts"]
        == timestamps[1]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("same", [True, False])
async def test_actual_simultaneous_send_serializes_same_route_only(
    runtime, slack_sdk, same
):
    rt = await slack(runtime, slack_sdk)
    first = await route(rt, "C123")
    second = await route(rt, "C123" if same else "D456")
    set_mode(slack_sdk.work, "chat.postMessage-block")
    one = asyncio.create_task(
        send(rt, first, parts=[{"type": "text", "text": "one"}])
    )
    await eventually(
        lambda: len(rows(slack_sdk.work, "chat.postMessage")) == 1
    )
    two = asyncio.create_task(
        send(rt, second, parts=[{"type": "text", "text": "two"}])
    )
    try:
        if same:
            await asyncio.sleep(0.1)
            assert len(rows(slack_sdk.work, "chat.postMessage")) == 1
        else:
            await eventually(
                lambda: len(rows(slack_sdk.work, "chat.postMessage")) == 2
            )
        set_mode(slack_sdk.work, "")
        assert all(
            result["state"] == "acknowledged"
            for result in await asyncio.gather(one, two)
        )
        assert len(rows(slack_sdk.work, "chat.postMessage")) == 2
    finally:
        set_mode(slack_sdk.work, "")
        await asyncio.gather(one, two, return_exceptions=True)
