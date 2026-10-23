"""Discord response ownership, stream receipts and unknown effects."""

import asyncio
import hashlib
import json

import pytest

from discord_suite import forbid_host_sdk
from discord_support import (
    discord,
    discord_sdk,
    eventually,
    fault_runtime,
    finish,
    identity,
    route,
    rows,
    runtime,
    send,
    set_mode,
)
from g2_official_process_suite import prepare


async def stream(
    rt,
    handle,
    operation,
    *,
    delivery_id,
    text,
    target=None,
    sequence=0,
    kind="message",
):
    return await send(
        rt,
        handle,
        operation="stream." + operation,
        delivery_id=delivery_id,
        accumulated_text=text,
        stream_type=kind,
        sequence=sequence,
        **({"target_delivery_id": target} if target else {}),
    )


@pytest.mark.asyncio
async def test_two_same_channel_responses_own_typing_independently(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    first, second = await route(rt), await route(rt)
    for handle in (first, first, second):
        assert (await prepare(rt, handle))["state"] == "acknowledged"
    assert len(rows(discord_sdk.work, "typing-enter")) == 2
    await finish(rt, first, "cancelled")
    assert len(rows(discord_sdk.work, "typing-exit")) == 1
    assert (await prepare(rt, second))["state"] == "acknowledged"
    assert len(rows(discord_sdk.work, "typing-enter")) == 2
    await finish(rt, second)
    assert len(rows(discord_sdk.work, "typing-exit")) == 2


@pytest.mark.asyncio
async def test_reasoning_and_message_streams_have_distinct_native_resources(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    handle = await route(rt)
    for kind in ("reasoning", "message"):
        result = await stream(
            rt, handle, "start", delivery_id=kind, text="...", kind=kind
        )
        assert result["state"] == "acknowledged"
    for kind, text in (("reasoning", "💭 thoughts"), ("message", "answer")):
        result = await stream(
            rt,
            handle,
            "end",
            delivery_id=kind + "-end",
            target=kind,
            text=text,
            kind=kind,
            sequence=1,
        )
        assert result["state"] == "acknowledged"
    sends, edits = rows(discord_sdk.work, "send"), rows(
        discord_sdk.work, "edit"
    )
    assert len(sends) == len(edits) == 2
    assert sends[0]["message_id"] != sends[1]["message_id"]
    assert [(row["message_id"], row["content"]) for row in edits] == [
        (sends[0]["message_id"], "💭 thoughts"),
        (sends[1]["message_id"], "answer"),
    ]
    await finish(rt, handle)
    assert len(rows(discord_sdk.work, "edit")) == 2


@pytest.mark.asyncio
async def test_stream_delta_tail_and_confirmed_delete_before_long_final(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    handle = await route(rt)
    assert (
        await stream(rt, handle, "start", delivery_id="start", text="...")
    )["state"] == "acknowledged"
    text = "a" * 2100 + "END"
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
        rows(discord_sdk.work, "edit")[-1]["content"] == "..." + text[-1996:]
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
        for row in rows(discord_sdk.work)
        if row["kind"] in {"send", "delete"}
    ]
    assert [row["kind"] for row in effects] == [
        "send",
        "delete",
        "send",
        "send",
    ]
    assert "".join(row["content"] for row in effects[2:]) == text
    assert all(len(row["content"]) <= 2000 for row in effects[2:])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,want",
    [
        ("delete-unknown", "unknown"),
        ("delete-server", "unknown"),
        ("delete-reject", "failed"),
        ("delete-missing", "failed"),
    ],
)
async def test_unconfirmed_placeholder_delete_never_sends_replacement(
    runtime, discord_sdk, mode, want
):
    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    handle = await route(rt)
    await stream(rt, handle, "start", delivery_id="start", text="...")
    set_mode(discord_sdk.work, mode)
    result = await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text="a" * 3000,
        sequence=1,
    )
    assert result["state"] == want
    assert len(rows(discord_sdk.work, "delete")) == 1
    assert len(rows(discord_sdk.work, "send")) == 1
    if want == "unknown":
        repeat = await stream(
            rt,
            handle,
            "end",
            delivery_id="repeat",
            target="start",
            text="a" * 3000,
            sequence=2,
        )
        assert repeat["state"] == "unknown"
        assert len(rows(discord_sdk.work, "delete")) == 1
        assert len(rows(discord_sdk.work, "send")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,want",
    [
        ("edit-unknown", "unknown"),
        ("edit-server", "unknown"),
        ("edit-missing", "failed"),
    ],
)
async def test_failed_or_unknown_final_edit_never_creates_fallback(
    runtime, discord_sdk, mode, want
):
    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    handle = await route(rt)
    await stream(rt, handle, "start", delivery_id="start", text="...")
    set_mode(discord_sdk.work, mode)
    result = await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text="answer",
        sequence=1,
    )
    assert result["state"] == want
    assert len(rows(discord_sdk.work, "send")) == 1
    assert len(rows(discord_sdk.work, "edit")) == 1


@pytest.mark.asyncio
async def test_unknown_delivery_duplicate_and_restart_never_replays_effect(
    runtime, discord_sdk
):
    from extension_process_suite import durable_snapshot
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
        receipt_path,
    )

    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    set_mode(discord_sdk.work, "send-unknown")
    for _ in range(2):
        result = await send(
            rt,
            handle,
            delivery_id="unknown",
            parts=[{"type": "text", "text": "one effect"}],
        )
        assert result["state"] == "unknown"
    assert len(rows(discord_sdk.work, "send")) == 1
    original = durable_snapshot(rt, handle)
    original_unknown = next(
        ref
        for ref in original["resource_refs"]
        if ref["kind"] == "discord.attempt" and ref["resource_id"] == "unknown"
    )
    assert original_unknown["attributes"]["state"] == "unknown"
    assert len(original_unknown["attributes"]["fingerprint"]) == 64
    await finish(rt, handle)
    await rt.loader.lifecycle.set_enabled("discord", False)
    set_mode(discord_sdk.work, "")
    await rt.loader.lifecycle.set_enabled("discord", True)
    rt.channel = await rt.manager.get_channel("discord")
    rt.process = rt.channel.channel_process
    result = await send(
        rt,
        handle,
        delivery_id="unknown",
        parts=[{"type": "text", "text": "one effect"}],
    )
    assert result["state"] == "unknown"
    assert len(rows(discord_sdk.work, "send")) == 1
    persisted = json.loads(rt.channel._state_path().read_text())
    assert all(
        row["response_handle"] != handle
        for row in persisted["discord.shared.responses"]["value"]
    )
    snapshot = ResponseReceiptStore(
        receipt_path(rt.ws.workspace_dir, "discord")
    ).get(receipt_key("discord.shared.responses", handle))
    assert snapshot["response_handle"] == handle
    assert snapshot["kind"] == "terminal"
    assert snapshot["cleanup_state"] == "complete"
    assert snapshot["resource_refs"] == [original_unknown]


@pytest.mark.asyncio
async def test_unknown_delta_blocks_finish_retry_and_different_delivery_replacement(
    runtime, discord_sdk
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    handle = await route(rt)
    other = await route(rt)
    await prepare(rt, handle)
    await prepare(rt, other)
    await stream(rt, handle, "start", delivery_id="start", text="...")
    set_mode(discord_sdk.work, "edit-unknown")
    result = await stream(
        rt,
        handle,
        "delta",
        delivery_id="delta",
        target="start",
        text="partial",
        sequence=1,
    )
    assert result["state"] == "unknown"
    set_mode(discord_sdk.work, "")
    result = await stream(
        rt,
        handle,
        "end",
        delivery_id="new-end",
        target="start",
        text="final",
        sequence=2,
    )
    assert result["state"] == "unknown"
    for _ in range(2):
        with pytest.raises(RpcError):
            await finish(rt, handle)
        assert len(rows(discord_sdk.work, "typing-exit")) == 1
    assert len(rows(discord_sdk.work, "edit")) == 1
    assert len(rows(discord_sdk.work, "send")) == 1
    assert (await prepare(rt, other))["state"] == "acknowledged"
    assert len(rows(discord_sdk.work, "typing-enter")) == 2
    await finish(rt, other)
    assert len(rows(discord_sdk.work, "typing-exit")) == 2


@pytest.mark.asyncio
async def test_stale_identity_cannot_prepare_or_send(runtime, discord_sdk):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    old = {**identity(rt), "generation": identity(rt)["generation"] + 1}
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.prepare",
            {
                **old,
                "response_handle": handle,
                "delivery_id": hashlib.sha256(
                    (handle + ":prepare").encode()
                ).hexdigest(),
            },
        )
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.send",
            {
                **old,
                "to_handle": handle,
                "delivery_id": "stale",
                "operation": "message.create",
                "content_parts": [{"type": "text", "text": "no effect"}],
            },
        )
    assert rows(discord_sdk.work, "typing-enter") == []
    assert rows(discord_sdk.work, "send") == []


@pytest.mark.asyncio
async def test_native_dm_long_stream_keeps_placeholder_channel_and_normal_reply_target(
    runtime, discord_sdk
):
    from discord_support import push

    rt = await discord(runtime, discord_sdk, streaming_enabled=True)
    push(discord_sdk.work, text="native DM")
    await eventually(lambda: len(rt.ws.requests) == 1)
    request = rt.ws.requests[0]
    assert request.session_id == "discord:dm:42"
    assert request.channel_meta["channel_id"] == "123"
    native_meta = {
        key: request.channel_meta[key]
        for key in ("channel_id", "user_id", "is_dm", "is_group")
    }
    handle = await route(rt, request.session_id, native_meta)
    assert (
        await stream(rt, handle, "start", delivery_id="start", text="...")
    )["state"] == "acknowledged"
    assert rows(discord_sdk.work, "send")[-1]["channel_id"] == 123
    assert (
        await stream(
            rt,
            handle,
            "end",
            delivery_id="end",
            target="start",
            text="a" * 3000,
            sequence=1,
        )
    )["state"] == "acknowledged"
    assert rows(discord_sdk.work, "delete")[-1]["channel_id"] == 123
    chunks = rows(discord_sdk.work, "send")[-2:]
    assert [row["channel_id"] for row in chunks] == [900042, 900042]
    assert "".join(row["content"] for row in chunks) == "a" * 3000
