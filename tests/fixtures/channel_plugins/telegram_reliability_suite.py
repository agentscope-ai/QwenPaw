"""Native SDK formatting fallback and unknown delivery custody."""

import asyncio

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_support import (
    eventually,
    fault_runtime,
    finish,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
    telegram,
    telegram_sdk,
)

TABLE = "| A | B |\n|---|---|\n| 1 | 2 |"


@pytest.mark.asyncio
async def test_rich_original_markdown_and_topic_reach_native_endpoint(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    await rt.channel.send("12345", TABLE, {"message_thread_id": 77})
    value = rows(telegram_sdk.work, "sendRichMessage")[-1]["arguments"]
    assert value["chat_id"] == 12345
    assert value["message_thread_id"] == 77
    assert value["rich_message"] == {"markdown": TABLE}
    assert rows(telegram_sdk.work, "sendMessage") == []


@pytest.mark.asyncio
async def test_native_missing_rich_endpoint_falls_back_once_to_html(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "sendRichMessage-missing")
    await rt.channel.send("12345", TABLE, {})
    assert len(rows(telegram_sdk.work, "sendRichMessage")) == 1
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1
    assert (
        rows(telegram_sdk.work, "sendMessage")[0]["arguments"]["parse_mode"]
        == "HTML"
    )


@pytest.mark.asyncio
async def test_explicit_native_entity_rejection_only_falls_back_before_effect(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "sendMessage-format")
    await rt.channel.send("12345", "**hello**", {})
    calls = rows(telegram_sdk.work, "sendMessage")
    assert len(calls) == 2
    assert calls[0]["arguments"]["text"] == "<b>hello</b>"
    assert calls[0]["arguments"]["parse_mode"] == "HTML"
    assert calls[1]["arguments"]["text"] == "hello"
    assert "parse_mode" not in calls[1]["arguments"]
    assert len(rows(telegram_sdk.work, "message-effect")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,text,mode,want_state",
    [
        ("sendRichMessage", TABLE, "sendRichMessage-server", "unknown"),
        ("sendRichMessage", TABLE, "sendRichMessage-timeout", "unknown"),
        ("sendMessage", "body", "sendMessage-server", "unknown"),
        ("sendMessage", "body", "sendMessage-reject", "failed"),
        ("sendMessage", "body", "sendMessage-unknown", "unknown"),
    ],
)
async def test_network_generic_badrequest_and_result_loss_never_replay(
    runtime, telegram_sdk, endpoint, text, mode, want_state
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, mode)
    meta = {}
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send("12345", text, meta)
    assert caught.value.state == want_state
    assert len(rows(telegram_sdk.work, endpoint)) == 1
    if endpoint == "sendRichMessage":
        assert rows(telegram_sdk.work, "sendMessage") == []
    if mode.endswith("-unknown"):
        assert caught.value.state == "unknown"
        assert meta["_reply_unknown"] is True
        original = dict(meta["_pending_delivery"])
        with pytest.raises(ChannelDeliveryError):
            await rt.channel.send("12345", text, meta)
        assert meta["_pending_delivery"] == original
        with pytest.raises(ChannelDeliveryError):
            await rt.channel.send("12345", text + " changed", meta)
        assert len(rows(telegram_sdk.work, endpoint)) == 1


@pytest.mark.asyncio
async def test_partial_send_format_failure_unknown_without_replay(
    runtime, telegram_sdk
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "sendMessage-second-reject")
    meta = {}
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send("12345", "A" * 8000, meta)
    assert caught.value.state == "unknown"
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2
    assert len(rows(telegram_sdk.work, "message-effect")) == 1
    assert (
        rows(telegram_sdk.work, "sendMessage")[0]["arguments"]["text"]
        == "A" * 4000
    )
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send("12345", "A" * 8000, meta)
    assert len(rows(telegram_sdk.work, "sendMessage")) == 2


@pytest.mark.asyncio
async def test_media_error_after_notice_keeps_operation_unknown(
    runtime, telegram_sdk
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "sendPhoto-server")
    parts = [
        {"type": "text", "text": "body"},
        {"type": "image", "image_url": "https://x.test/i"},
    ]
    meta = {}
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send_content_parts("12345", parts, meta)
    assert caught.value.state == "unknown"
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1
    assert len(rows(telegram_sdk.work, "sendPhoto")) == 1
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send_content_parts("12345", parts, meta)
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1
    assert len(rows(telegram_sdk.work, "sendPhoto")) == 1


@pytest.mark.asyncio
async def test_first_native_send_rpc_cancel_keeps_public_pending_custody(
    runtime, telegram_sdk
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await telegram(runtime, telegram_sdk)
    set_mode(telegram_sdk.work, "sendMessage-finally-block")
    meta = {}
    task = asyncio.create_task(
        rt.channel.send("12345", "uncertain first", meta)
    )
    await eventually(lambda: bool(rows(telegram_sdk.work, "message-effect")))
    started = asyncio.get_running_loop().time()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert asyncio.get_running_loop().time() - started < 8
    assert meta["response_handle"]
    assert meta["_pending_delivery"]["delivery_id"]
    assert meta["_reply_unknown"] is True
    set_mode(telegram_sdk.work, "")
    await eventually(lambda: bool(rows(telegram_sdk.work, "sendMessage-exit")))
    with pytest.raises(ChannelDeliveryError):
        await rt.channel.send("12345", "changed payload", meta)
    assert len(rows(telegram_sdk.work, "message-effect")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("status", [400, 404])
async def test_legacy_rich_fallback_keeps_exact_table_code_path_and_link(
    runtime, telegram_sdk, streaming, status
):
    from discord_stream_suite import stream

    rt = await telegram(runtime, telegram_sdk, streaming_enabled=streaming)
    text = (
        "| Code | Value |\n|---|---|\n"
        "| `__init__` | `C:\\my_project_dir` |\n"
        "| Manual | [Manual](https://docs.python.org/3/) |"
    )
    handle = None
    if streaming:
        handle = await route(rt, "12345", {"message_thread_id": 77})
        assert (
            await stream(rt, handle, "start", delivery_id="start", text="")
        )["state"] == "acknowledged"
    set_mode(telegram_sdk.work, "rich-unavailable-" + str(status))
    if streaming:
        result = await stream(
            rt,
            handle,
            "end",
            delivery_id="end",
            target="start",
            text=text,
            sequence=1,
        )
        assert result["state"] == "acknowledged"
        calls = rows(telegram_sdk.work, "editMessageText")
        rich = [r for r in calls if "rich_message" in r["arguments"]]
        legacy = [r for r in calls if "rich_message" not in r["arguments"]]
        assert len(rows(telegram_sdk.work, "sendMessage")) == 1
        assert rows(telegram_sdk.work, "sendRichMessage") == []
    else:
        await rt.channel.send("12345", text, {"message_thread_id": 77})
        rich = rows(telegram_sdk.work, "sendRichMessage")
        legacy = rows(telegram_sdk.work, "sendMessage")
        assert rows(telegram_sdk.work, "editMessageText") == []
    assert len(rich) == 1
    assert rich[0]["arguments"]["rich_message"] == {"markdown": text}
    assert len(legacy) == 1
    kwargs = legacy[0]["arguments"]
    assert kwargs["parse_mode"] == "HTML"
    assert "<pre>" not in kwargs["text"]
    assert "|---|---|" in kwargs["text"]
    assert "<code>__init__</code>" in kwargs["text"]
    assert "<code>C:\\my_project_dir</code>" in kwargs["text"]
    assert 'href="https://docs.python.org/3/"' in kwargs["text"]
    if handle is not None:
        await finish(rt, handle)
