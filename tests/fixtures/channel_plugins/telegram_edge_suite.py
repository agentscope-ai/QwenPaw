"""Closed native admission boundaries for obsolete empty/invalid inputs."""

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_support import (
    fault_runtime,
    finish,
    route,
    rows,
    runtime,
    send,
    telegram,
    telegram_sdk,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "part",
    [
        {"type": "unknown", "image_url": "https://x.test/i"},
        {"type": "image", "image_url": ""},
        {"type": "file", "file_url": ""},
    ],
)
async def test_invalid_media_wire_is_rejected_before_any_native_effect(
    runtime, telegram_sdk, part
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await telegram(runtime, telegram_sdk)
    handle = await route(rt, "12345")
    with pytest.raises(RpcError) as caught:
        await send(rt, handle, parts=[part], content_source="media")
    assert caught.value.code == -32602
    assert caught.value.data["reason_code"] == "INVALID_PARAMS"
    assert rows(telegram_sdk.work, "sendMessage") == []
    for endpoint in ("sendPhoto", "sendVideo", "sendAudio", "sendDocument"):
        assert rows(telegram_sdk.work, endpoint) == []
    await finish(rt, handle)


@pytest.mark.asyncio
async def test_empty_route_is_rejected_before_any_native_send(
    runtime, telegram_sdk
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await telegram(runtime, telegram_sdk)
    with pytest.raises(RpcError) as caught:
        await route(rt, "")
    assert caught.value.code == -32603
    assert caught.value.message == "internal error"
    assert rows(telegram_sdk.work, "sendMessage") == []
    assert rows(telegram_sdk.work, "sendPhoto") == []


@pytest.mark.asyncio
async def test_unknown_card_delivery_never_creates_clickable_authority(
    runtime, telegram_sdk, monkeypatch
):
    from telegram_cards_suite import click
    from telegram_support import bind_telegram_runtime, set_mode

    rt = await telegram(runtime, telegram_sdk)
    host = await bind_telegram_runtime(rt, monkeypatch)
    handle = await route(rt, "12345", {"user_id": "456"})
    set_mode(telegram_sdk.work, "sendMessage-unknown")
    fields = {
        "approval": {
            "request_id": "uncertain-card",
            "tool_name": "shell",
            "severity": "high",
        },
        "parts": [{"type": "text", "text": "uncertain card"}],
        "delivery_id": "uncertain-card-send",
    }
    first = await send(rt, handle, **fields)
    assert first["state"] == "unknown"
    message = rows(telegram_sdk.work, "message-effect")[0]["message"]

    class RequestId:
        request_id = "uncertain-card"

    click(telegram_sdk, RequestId(), message)
    from telegram_support import eventually

    await eventually(
        lambda: bool(rows(telegram_sdk.work, "answerCallbackQuery"))
    )
    assert (
        rows(telegram_sdk.work, "answerCallbackQuery")[0]["arguments"]["text"]
        == "This approval button has expired."
    )
    assert rt.ws.requests == []
    assert host.calls == []
    assert rows(telegram_sdk.work, "editMessageText") == []
    assert await send(rt, handle, **fields) == first
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1


@pytest.mark.asyncio
async def test_worker_policy_keeps_the_five_legacy_format_flags(
    runtime, telegram_sdk
):
    from qwenpaw.channel_protocol.response_policy import ResponsePolicy
    from telegram_support import identity

    rt = await telegram(runtime, telegram_sdk)
    handle = await route(rt, "12345")
    policy = ResponsePolicy.from_mapping(
        await rt.process.call(
            "channel.response.describe",
            {**identity(rt), "response_handle": handle},
        )
    )
    assert policy.streaming is False
    assert policy.prepare is True
    assert policy.completion_reaction is False
    value = policy.send_format
    assert (
        value.direct_prefix,
        value.parts_configured_prefix,
        value.parts_metadata_prefix,
        value.stream_prefix,
        value.parts_strip_text,
    ) == (False, False, True, False, False)
    await finish(rt, handle)


@pytest.mark.asyncio
async def test_sparse_host_approval_event_keeps_tool_defaults_and_placeholder(
    runtime, telegram_sdk
):
    from qwenpaw.schemas import AgentRequest, Message

    rt = await telegram(runtime, telegram_sdk)
    handle = await route(rt, "12345", {"user_id": "456"})
    seen = []
    original = rt.process.call

    async def observe(method, params, **kwargs):
        if method == "channel.send":
            seen.append(params)
        return await original(method, params, **kwargs)

    rt.process.call = observe
    event = Message(
        object="message",
        status="completed",
        role="assistant",
        content=[],
        metadata={
            "message_type": "tool_guard_approval",
            "approval_request_id": "sparse-card",
        },
    )
    await rt.channel.on_event_message_completed(
        AgentRequest(
            user_id="456", session_id="telegram:12345", channel="telegram"
        ),
        "12345",
        event,
        {"response_handle": handle},
    )
    assert seen[-1]["approval"] == {
        "request_id": "sparse-card",
        "tool_name": "tool",
        "severity": "medium",
    }
    message = rows(telegram_sdk.work, "message-effect")[0]["message"]
    assert message["text"] == "🛡️ Tool Approval Required"
    assert message.get("message_thread_id") is None
    assert (
        message["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        == "tga:sparse-card"
    )
    await finish(rt, handle)
