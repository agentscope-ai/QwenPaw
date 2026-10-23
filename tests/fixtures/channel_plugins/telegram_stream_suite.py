"""Owned native Telegram placeholders, edits, throttle and typing cleanup."""

import asyncio

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_support import (
    eventually,
    fault_runtime,
    finish,
    identity,
    route,
    rows,
    runtime,
    send,
    set_mode,
    telegram,
    telegram_sdk,
)
from discord_stream_suite import stream
from g2_official_process_suite import prepare


@pytest.mark.asyncio
async def test_base_event_consumer_throttles_delta_and_final_keeps_all_text(
    runtime, telegram_sdk
):
    from qwenpaw.schemas import Message, TextContent, RunStatus

    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    meta, types, buffers = {}, {}, {}
    start = Message(
        id="stream-A", object="message", status=RunStatus.InProgress
    )
    assert await rt.channel._dispatch_streaming_event(
        None, "12345", start, meta, types, buffers
    )
    first = TextContent(
        object="content", msg_id="stream-A", delta=True, text="one"
    )
    assert await rt.channel._dispatch_streaming_event(
        None, "12345", first, meta, types, buffers
    )
    await eventually(
        lambda: len(rows(telegram_sdk.work, "editMessageText")) == 1
    )
    await asyncio.sleep(0.01)
    for text in ("two", "three"):
        delta = TextContent(
            object="content", msg_id="stream-A", delta=True, text=text
        )
        assert await rt.channel._dispatch_streaming_event(
            None, "12345", delta, meta, types, buffers
        )
    await asyncio.sleep(0.1)
    assert len(rows(telegram_sdk.work, "editMessageText")) == 1
    end = Message(id="stream-A", object="message", status=RunStatus.Completed)
    assert await rt.channel._dispatch_streaming_event(
        None, "12345", end, meta, types, buffers
    )
    edits = rows(telegram_sdk.work, "editMessageText")
    assert edits[-1]["arguments"]["text"] == "onetwothree"
    deltas = [v for v in edits if "parse_mode" not in v["arguments"]]
    assert all(
        right["at"] - left["at"] >= 1.5
        for left, right in zip(deltas, deltas[1:])
    )


@pytest.mark.asyncio
async def test_host_message_reasoning_placeholders_and_final_text_are_exact(
    runtime, telegram_sdk
):
    rt = await telegram(
        runtime, telegram_sdk, streaming_enabled=True, bot_prefix="CONFIG"
    )
    meta = {"bot_prefix": "META", "message_thread_id": 77}
    for kind in ("reasoning", "message"):
        await rt.channel.on_streaming_start(None, "12345", None, meta, kind)
        await rt.channel.on_streaming_delta(
            None, "12345", None, meta, kind, "**one**"
        )
        await rt.channel.on_streaming_end(
            None, "12345", None, meta, kind, "**final**"
        )
    assert [
        v["arguments"]["text"] for v in rows(telegram_sdk.work, "sendMessage")
    ] == ["💭 ⏳", "⏳"]
    edits = rows(telegram_sdk.work, "editMessageText")
    assert [v["arguments"]["text"] for v in edits] == [
        "💭 **one**",
        "💭 <b>final</b>",
        "**one**",
        "<b>final</b>",
    ]
    assert (
        edits[0]["arguments"]["message_id"]
        != edits[2]["arguments"]["message_id"]
    )
    assert all(
        v["arguments"]["message_thread_id"] == 77
        for v in rows(telegram_sdk.work, "sendMessage")
    )
    await finish(rt, meta["response_handle"])
    assert rows(telegram_sdk.work, "deleteMessage") == []


@pytest.mark.asyncio
async def test_throttle_is_per_owned_message_and_final_edit_is_unconditional(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    first, second = await route(rt, "12345"), await route(rt, "12345")
    for handle, name in ((first, "first"), (second, "second")):
        await stream(rt, handle, "start", delivery_id=name, text="")
    for number, text in ((1, "one"), (2, "two")):
        await stream(
            rt,
            first,
            "delta",
            delivery_id="first-" + str(number),
            target="first",
            text=text,
            sequence=number,
        )
    edits = rows(telegram_sdk.work, "editMessageText")
    assert len(edits) == 2
    assert edits[1]["at"] - edits[0]["at"] >= 1.5
    await stream(
        rt,
        second,
        "delta",
        delivery_id="second-1",
        target="second",
        text="other",
        sequence=1,
    )
    assert len(rows(telegram_sdk.work, "editMessageText")) == 3
    await stream(
        rt,
        first,
        "end",
        delivery_id="first-end",
        target="first",
        text="final",
        sequence=3,
    )
    assert (
        rows(telegram_sdk.work, "editMessageText")[-1]["arguments"]["text"]
        == "final"
    )
    assert len(rows(telegram_sdk.work, "editMessageText")) == 4


@pytest.mark.asyncio
async def test_delta_tail_long_final_confirmed_delete_then_chunks(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    handle = await route(rt, "12345")
    await stream(rt, handle, "start", delivery_id="start", text="")
    text = "a" * 5000 + "END"
    await stream(
        rt,
        handle,
        "delta",
        delivery_id="delta",
        target="start",
        text=text,
        sequence=1,
    )
    delta = rows(telegram_sdk.work, "editMessageText")[-1]["arguments"]
    assert delta["text"] == "..." + text[-4092:]
    await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text=text,
        sequence=2,
    )
    calls = rows(telegram_sdk.work)
    deleted = next(
        i
        for i, value in enumerate(calls)
        if value["kind"] == "deleteMessage-exit"
    )
    finals = [
        i for i, value in enumerate(calls) if value["kind"] == "sendMessage"
    ][1:]
    assert len(finals) == 2
    assert all(i > deleted for i in finals)
    assert "".join(calls[i]["arguments"]["text"] for i in finals) == text


@pytest.mark.asyncio
async def test_rich_stream_final_uses_native_edit_rich_markdown(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    handle = await route(rt, "12345")
    await stream(rt, handle, "start", delivery_id="start", text="")
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text=table,
        sequence=1,
    )
    edit = rows(telegram_sdk.work, "editMessageText")[-1]["arguments"]
    assert edit["rich_message"] == {"markdown": table}
    assert rows(telegram_sdk.work, "sendRichMessage") == []
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1


@pytest.mark.asyncio
async def test_same_chat_cancellation_removes_only_its_confirmed_placeholder(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    first, second = await route(rt, "12345"), await route(rt, "12345")
    await stream(rt, first, "start", delivery_id="first", text="")
    await stream(rt, second, "start", delivery_id="second", text="")
    messages = rows(telegram_sdk.work, "message-effect")
    first_id, second_id = [v["message"]["message_id"] for v in messages]
    await finish(rt, first, "cancelled")
    deletes = rows(telegram_sdk.work, "deleteMessage")
    assert [v["arguments"]["message_id"] for v in deletes] == [first_id]
    await stream(
        rt,
        second,
        "end",
        delivery_id="second-end",
        target="second",
        text="still alive",
        sequence=1,
    )
    assert (
        rows(telegram_sdk.work, "editMessageText")[-1]["arguments"][
            "message_id"
        ]
        == second_id
    )
    assert len(rows(telegram_sdk.work, "deleteMessage")) == 1


@pytest.mark.asyncio
async def test_unknown_holder_final_edit_never_guesses_delete_new_message(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    handle = await route(rt, "12345")
    set_mode(telegram_sdk.work, "sendMessage-unknown")
    result = await stream(rt, handle, "start", delivery_id="start", text="")
    assert result["state"] == "unknown"
    result = await finish(rt, handle, "cancelled")
    assert result["outcome"] == "cancelled"
    assert rows(telegram_sdk.work, "deleteMessage") == []
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1


@pytest.mark.asyncio
async def test_unknown_rich_final_edit_keeps_payload_never_deletes_falls_back(
    runtime, telegram_sdk
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    handle = await route(rt, "12345")
    await stream(rt, handle, "start", delivery_id="start", text="")
    set_mode(telegram_sdk.work, "editMessageText-unknown")
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    first = await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text=table,
        sequence=1,
    )
    assert first["state"] == "unknown"
    second = await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text=table,
        sequence=1,
    )
    assert second == first
    with pytest.raises(RpcError) as caught:
        await finish(rt, handle, "cancelled")
    assert caught.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    assert len(rows(telegram_sdk.work, "editMessageText")) == 1
    assert rows(telegram_sdk.work, "editMessageText")[0]["arguments"][
        "rich_message"
    ] == {"markdown": table}
    assert rows(telegram_sdk.work, "deleteMessage") == []
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1


@pytest.mark.asyncio
async def test_long_final_delete_unknown_never_sends_chunks_or_redeletes(
    runtime, telegram_sdk
):
    from qwenpaw.plugins.execution.errors import RpcError

    rt = await telegram(runtime, telegram_sdk, streaming_enabled=True)
    handle = await route(rt, "12345")
    await stream(rt, handle, "start", delivery_id="start", text="")
    set_mode(telegram_sdk.work, "deleteMessage-timeout")
    result = await stream(
        rt,
        handle,
        "end",
        delivery_id="end",
        target="start",
        text="x" * 5000,
        sequence=1,
    )
    assert result["state"] == "unknown"
    with pytest.raises(RpcError):
        await finish(rt, handle, "cancelled")
    assert len(rows(telegram_sdk.work, "deleteMessage")) == 1
    assert len(rows(telegram_sdk.work, "sendMessage")) == 1


@pytest.mark.asyncio
async def test_typing_native_request_exits_before_response_cleanup_finishes(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, show_typing=True)
    handle = await route(rt, "12345")
    set_mode(telegram_sdk.work, "sendChatAction-block")
    result = await prepare(rt, handle)
    assert result["state"] == "acknowledged"
    await eventually(lambda: bool(rows(telegram_sdk.work, "sendChatAction")))
    result = await finish(rt, handle, "cancelled")
    assert result["outcome"] == "cancelled"
    starts, exits = rows(telegram_sdk.work, "sendChatAction"), rows(
        telegram_sdk.work, "sendChatAction-exit"
    )
    assert {v["task"] for v in starts} == {v["task"] for v in exits}
    assert rows(telegram_sdk.work, "sendChatAction-cancelled")


@pytest.mark.asyncio
async def test_same_chat_two_typing_owners_repeat_prepare_cancel_request(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, show_typing=True)
    first, second = await route(rt, "12345"), await route(rt, "12345")
    set_mode(telegram_sdk.work, "sendChatAction-block")
    assert (await prepare(rt, first))["state"] == "acknowledged"
    assert (await prepare(rt, first))["state"] == "acknowledged"
    assert (await prepare(rt, second))["state"] == "acknowledged"
    await eventually(
        lambda: len(rows(telegram_sdk.work, "sendChatAction")) == 2
    )
    await finish(rt, first, "cancelled")
    assert len(rows(telegram_sdk.work, "sendChatAction-exit")) == 1
    await finish(rt, second, "cancelled")
    assert len(rows(telegram_sdk.work, "sendChatAction-exit")) == 2


@pytest.mark.asyncio
async def test_typing_disabled_policy_does_not_start_native_action_for_reply(
    runtime, telegram_sdk
):
    from telegram_support import push

    await telegram(runtime, telegram_sdk, show_typing=False)
    push(telegram_sdk.work)
    await eventually(lambda: bool(rows(telegram_sdk.work, "sendMessage")))
    assert rows(telegram_sdk.work, "sendChatAction") == []


@pytest.mark.asyncio
async def test_native_typing_failure_does_not_drop_real_reply_or_leak_request(
    runtime, telegram_sdk
):
    rt = await telegram(runtime, telegram_sdk, show_typing=True)
    set_mode(telegram_sdk.work, "sendChatAction-server")
    handle = await route(rt, "12345")
    await prepare(rt, handle)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "sendChatAction-exit"))
    )
    await send(
        rt,
        handle,
        parts=[{"type": "text", "text": "reply after typing error"}],
    )
    await finish(rt, handle)
    assert (
        rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["text"]
        == "reply after typing error"
    )
    assert (
        len(rows(telegram_sdk.work, "sendChatAction"))
        == len(rows(telegram_sdk.work, "sendChatAction-exit"))
        == 1
    )
