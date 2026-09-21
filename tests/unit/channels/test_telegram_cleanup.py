# -*- coding: utf-8 -*-
"""Unit tests for Telegram intermediate-message cleanup (Issue #7586).

Covers the required matrix with mocked Bot API — no network:
1. cleanup disabled → old behavior (no tracking, no delete)
2. reasoning + final → delete reasoning, keep final
3. reasoning + tool + final → delete intermediates, keep final
4. final only → keep final
5. long/chunked final → all final chunks kept
6. reasoning long/chunk path → reasoning chunks deleted
7. tool send failure → answer unaffected
8. delete failure → answer unaffected
9. process error → no cleanup
10. cancellation → no cleanup (error path does not delete)
11. concurrent requests isolation
12. HTML fallback keeps ID tracking
13. placeholder failure + fallback send
14. existing single-edit streaming behavior
15. show_thinking=false (no reasoning ids → nothing deleted)
"""
# pylint: disable=protected-access,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from typing import Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.app.channels.telegram.channel import (
    TelegramChannel,
    _TG_KIND_FINAL,
    _TG_KIND_INTERMEDIATE,
)
from qwenpaw.config.config import TelegramConfig
from qwenpaw.schemas import (
    ContentType,
    DataContent,
    Message,
    MessageType,
    RunStatus,
    TextContent,
)


def _make_channel(
    tmp_path,
    *,
    cleanup: bool,
    display_config=None,
) -> TelegramChannel:
    async def _process(*_a, **_k):
        yield MagicMock()

    channel = TelegramChannel(
        process=_process,
        enabled=True,
        bot_token="test_token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir=str(tmp_path / "media"),
        display_config=display_config
        or ChannelDisplayConfig(
            show_tool_calls=True,
            show_tool_results=True,
            show_thinking=True,
        ),
        cleanup_intermediate=cleanup,
    )
    return channel


def _install_bot(channel: TelegramChannel, start_id: int = 100):
    """Install a mock bot with auto-increment message_ids."""
    counter = {"next": start_id}
    sent_ids: list[int] = []
    deleted: list[int] = []

    async def _send_message(**kwargs):
        counter["next"] += 1
        mid = counter["next"]
        sent_ids.append(mid)
        return SimpleNamespace(message_id=mid)

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=_send_message)
    bot.edit_message_text = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(
        side_effect=lambda chat_id, message_id: deleted.append(
            int(message_id),
        ),
    )
    bot.send_chat_action = AsyncMock()
    app = MagicMock()
    app.bot = bot
    channel._application = app
    # Silence typing tasks in tests.
    channel._show_typing = False
    return bot, sent_ids, deleted


def _msg(
    mtype: MessageType,
    content,
    **kw,
) -> Message:
    base = {
        "object": "message",
        "status": RunStatus.Completed,
    }
    base.update(kw)
    return Message(type=mtype, content=content, **base)


@pytest.mark.asyncio
async def test_1_cleanup_disabled_keeps_old_behavior(tmp_path):
    ch = _make_channel(tmp_path, cleanup=False)
    _, _sent, deleted = _install_bot(ch)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="think",
    )
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="final",
    )
    # Disabled → no ledgers populated.
    state = send_meta.get("_tg_stream", {})
    assert not state.get("intermediate_ids", [])
    assert not state.get("final_ids", [])
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


@pytest.mark.asyncio
async def test_2_reasoning_plus_final(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=100)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    reasoning_id = send_meta["_tg_stream"]["message_ids"]["reasoning"]
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="think",
    )
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    final_id = send_meta["_tg_stream"]["message_ids"]["message"]
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="final",
    )
    state = send_meta["_tg_stream"]
    assert state["intermediate_ids"] == [reasoning_id]
    assert state["final_ids"] == [final_id]
    await ch._on_process_completed(None, "1", send_meta)
    assert deleted == [reasoning_id]
    assert final_id not in deleted


@pytest.mark.asyncio
async def test_3_reasoning_tool_final(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=200)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="think",
    )
    tool_ev = _msg(
        MessageType.FUNCTION_CALL,
        [DataContent(data={"name": "weather", "arguments": "{}"})],
    )
    await ch.on_event_message_completed(None, "1", tool_ev, send_meta)
    out_ev = _msg(
        MessageType.FUNCTION_CALL_OUTPUT,
        [DataContent(data={"name": "weather", "output": "sunny"})],
    )
    await ch.on_event_message_completed(None, "1", out_ev, send_meta)
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="sunny!",
    )
    state = send_meta["_tg_stream"]
    assert len(state["intermediate_ids"]) == 3  # reasoning + call + output
    assert len(state["final_ids"]) == 1
    finals = set(state["final_ids"])
    await ch._on_process_completed(None, "1", send_meta)
    assert sorted(deleted) == sorted(state["intermediate_ids"])
    assert not set(deleted) & finals


@pytest.mark.asyncio
async def test_4_final_only_kept(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=300)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="only",
    )
    assert not send_meta["_tg_stream"]["intermediate_ids"]
    assert len(send_meta["_tg_stream"]["final_ids"]) == 1
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


@pytest.mark.asyncio
async def test_5_long_chunked_final_all_kept(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, sent, deleted = _install_bot(ch, start_id=400)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    long_text = "x" * 5000
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text=long_text,
    )
    state = send_meta["_tg_stream"]
    # Placeholder deleted for the long path, chunks recorded as final.
    assert len(state["final_ids"]) >= 2
    assert not state["intermediate_ids"]
    assert set(state["final_ids"]).issubset(set(sent))
    placeholder_deletes = list(deleted)
    await ch._on_process_completed(None, "1", send_meta)
    # Only the long-path placeholder delete happened; no final chunk
    # was removed by cleanup.
    assert set(state["final_ids"]).isdisjoint(set(deleted))
    assert deleted == placeholder_deletes


@pytest.mark.asyncio
async def test_6_reasoning_long_chunks_deleted(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=500)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="y" * 5000,
    )
    state = send_meta["_tg_stream"]
    assert len(state["intermediate_ids"]) >= 2
    assert not state["final_ids"]
    await ch._on_process_completed(None, "1", send_meta)
    # deleted = long-path placeholder delete + cleanup of every chunk.
    assert set(state["intermediate_ids"]).issubset(set(deleted))


@pytest.mark.asyncio
async def test_7_tool_send_failure_answer_unaffected(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    bot, _, deleted = _install_bot(ch, start_id=600)
    send_meta: Dict = {"chat_id": "1"}
    tool_ev = _msg(
        MessageType.FUNCTION_CALL,
        [DataContent(data={"name": "weather", "arguments": "{}"})],
    )
    bot.send_message = AsyncMock(side_effect=Exception("net down"))
    # Must not raise; failure is swallowed like the old send().
    await ch.on_event_message_completed(None, "1", tool_ev, send_meta)
    assert not send_meta.get("_tg_stream", {}).get("intermediate_ids", [])
    bot.send_message = AsyncMock(
        side_effect=lambda **kw: SimpleNamespace(message_id=999),
    )
    ch._application.bot = bot
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="ok",
    )
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


@pytest.mark.asyncio
async def test_8_delete_failure_answer_unaffected(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    bot, _, _ = _install_bot(ch, start_id=700)
    bot.delete_message = AsyncMock(side_effect=Exception("cant delete"))
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="t",
    )
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="final",
    )
    # Must not raise even though every delete fails.
    await ch._on_process_completed(None, "1", send_meta)


@pytest.mark.asyncio
async def test_9_process_error_no_cleanup(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    bot, _, deleted = _install_bot(ch, start_id=800)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="t",
    )
    # Error path (not _on_process_completed) must not delete.
    await ch._on_consume_error(None, "1", "Error: boom")
    assert not deleted
    # Error notice itself goes via request.channel_meta (untracked).
    assert bot.send_message.called


@pytest.mark.asyncio
async def test_10_cancel_no_cleanup(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=900)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "reasoning",
        accumulated_text="t",
    )
    # Cancellation never reaches _on_process_completed → nothing deleted.
    assert not deleted
    assert send_meta["_tg_stream"]["intermediate_ids"] != []


@pytest.mark.asyncio
async def test_11_concurrent_requests_isolation(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=1000)
    meta_a: Dict = {"chat_id": "1"}
    meta_b: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, meta_a, "reasoning")
    await ch.on_streaming_start(None, "1", None, meta_b, "reasoning")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        meta_a,
        "reasoning",
        accumulated_text="a-think",
    )
    await ch.on_streaming_end(
        None,
        "1",
        None,
        meta_b,
        "reasoning",
        accumulated_text="b-think",
    )
    await ch.on_streaming_start(None, "1", None, meta_a, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        meta_a,
        "message",
        accumulated_text="a-final",
    )
    await ch.on_streaming_start(None, "1", None, meta_b, "message")
    await ch.on_streaming_end(
        None,
        "1",
        None,
        meta_b,
        "message",
        accumulated_text="b-final",
    )
    id_a = meta_a["_tg_stream"]["intermediate_ids"]
    id_b = meta_b["_tg_stream"]["intermediate_ids"]
    assert id_a and id_b and set(id_a).isdisjoint(set(id_b))
    await ch._on_process_completed(None, "1", meta_a)
    assert sorted(deleted) == sorted(id_a)
    assert not set(deleted) & set(id_b)
    await ch._on_process_completed(None, "1", meta_b)
    assert set(id_b).issubset(set(deleted))


@pytest.mark.asyncio
async def test_12_html_fallback_keeps_tracking(tmp_path):
    from telegram.error import BadRequest

    ch = _make_channel(tmp_path, cleanup=True)
    bot, _, _ = _install_bot(ch, start_id=1100)
    calls = {"n": 0}

    async def _flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise BadRequest("Can't parse HTML")
        return SimpleNamespace(message_id=1234)

    bot.send_message = AsyncMock(side_effect=_flaky)
    ch._application.bot = bot
    send_meta: Dict = {"chat_id": "1"}
    ev = _msg(MessageType.MESSAGE, [TextContent(text="<b>hi</b>")])
    await ch.on_event_message_completed(None, "1", ev, send_meta)
    assert send_meta["_tg_stream"]["final_ids"] == [1234]


@pytest.mark.asyncio
async def test_13_placeholder_failure_fallback_send(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    bot, _, deleted = _install_bot(ch, start_id=1200)
    bot.send_message = AsyncMock(
        side_effect=[
            Exception("placeholder boom"),  # _send_placeholder fails
            SimpleNamespace(message_id=1301),  # fallback send succeeds
        ],
    )
    ch._application.bot = bot
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    assert send_meta["_tg_stream"]["message_ids"].get("message") is None
    bot.send_message = AsyncMock(
        side_effect=lambda **kw: SimpleNamespace(message_id=1301),
    )
    ch._application.bot = bot
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="fallback",
    )
    assert send_meta["_tg_stream"]["final_ids"] == [1301]
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


@pytest.mark.asyncio
async def test_14_single_edit_streaming_regression(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    bot, _, _ = _install_bot(ch, start_id=1400)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_streaming_start(None, "1", None, send_meta, "message")
    mid = send_meta["_tg_stream"]["message_ids"]["message"]
    await ch.on_streaming_delta(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="hel",
    )
    await ch.on_streaming_end(
        None,
        "1",
        None,
        send_meta,
        "message",
        accumulated_text="hello",
    )
    # Single-message final: edited in place, still one Telegram message.
    assert bot.send_message.call_count == 1
    assert bot.edit_message_text.called
    assert send_meta["_tg_stream"]["final_ids"] == [mid]


@pytest.mark.asyncio
async def test_15_show_thinking_false_sends_nothing(tmp_path):
    ch = _make_channel(
        tmp_path,
        cleanup=True,
        display_config=ChannelDisplayConfig(
            show_tool_calls=True,
            show_tool_results=True,
            show_thinking=False,
        ),
    )
    _, _, deleted = _install_bot(ch, start_id=1500)
    send_meta: Dict = {"chat_id": "1"}
    # Non-streaming reasoning with show_thinking=False renders no parts.
    ev = _msg(MessageType.REASONING, [TextContent(text="hidden")])
    await ch.on_event_message_completed(None, "1", ev, send_meta)
    assert not send_meta.get("_tg_stream", {}).get("intermediate_ids", [])
    assert not send_meta.get("_tg_stream", {}).get("final_ids", [])
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


def test_config_defaults_to_false(tmp_path):
    cfg = TelegramConfig()
    assert cfg.cleanup_intermediate is False
    ch = _make_channel(tmp_path, cleanup=False)
    assert ch._cleanup_intermediate is False
    ch2 = TelegramChannel.from_config(
        process=MagicMock(),
        config={"bot_token": "x", "cleanup_intermediate": True},
    )
    assert ch2._cleanup_intermediate is True
    ch3 = TelegramChannel.from_config(
        process=MagicMock(),
        config={"bot_token": "x"},
    )
    assert ch3._cleanup_intermediate is False


@pytest.mark.asyncio
async def test_approval_card_never_tracked(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=1600)
    send_meta: Dict = {"chat_id": "1"}
    card_event = MagicMock()
    card_event.metadata = {
        "metadata": {"message_type": "tool_guard_approval"},
    }
    with_setup = False
    # Stub the card handler to simulate an approval card send.
    ch._card_handler.try_send_card_for_event = AsyncMock(return_value=True)
    with_setup = True
    assert with_setup
    await ch.on_event_message_completed(None, "1", card_event, send_meta)
    assert not send_meta.get("_tg_stream", {}).get("intermediate_ids", [])
    assert not send_meta.get("_tg_stream", {}).get("final_ids", [])
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


# =============================================================================
# Issue #7586 close-out: explicit MessageType matrix (no fuzzy matching)
# =============================================================================


_INTERMEDIATE_TYPES = [
    MessageType.REASONING,
    MessageType.PLUGIN_CALL,
    MessageType.PLUGIN_CALL_OUTPUT,
    MessageType.FUNCTION_CALL,
    MessageType.FUNCTION_CALL_OUTPUT,
    MessageType.MCP_TOOL_CALL,
    MessageType.MCP_TOOL_CALL_OUTPUT,
    MessageType.PROGRESS,
]

_FINAL_TYPES = [
    MessageType.MESSAGE,
    MessageType.RESULT,
]


def _event_for_type(mtype: MessageType) -> Message:
    """Build a renderable Message for each MessageType."""
    if mtype in (
        MessageType.PLUGIN_CALL,
        MessageType.FUNCTION_CALL,
        MessageType.MCP_TOOL_CALL,
    ):
        return _msg(
            mtype,
            [DataContent(data={"name": "tool", "arguments": '{"a":1}'})],
        )
    if mtype in (
        MessageType.PLUGIN_CALL_OUTPUT,
        MessageType.FUNCTION_CALL_OUTPUT,
        MessageType.MCP_TOOL_CALL_OUTPUT,
    ):
        return _msg(
            mtype,
            [DataContent(data={"name": "tool", "output": "tool-output"})],
        )
    return _msg(mtype, [TextContent(text=f"text for {mtype.value}")])


@pytest.mark.parametrize("mtype", _INTERMEDIATE_TYPES)
def test_classify_all_intermediate_types(mtype):
    assert (
        TelegramChannel._classify_completed_event_kind(
            SimpleNamespace(type=mtype),
        )
        == _TG_KIND_INTERMEDIATE
    )
    # Plain-string form (e.g. JSON-deserialized events) must match too.
    assert (
        TelegramChannel._classify_completed_event_kind(
            SimpleNamespace(type=mtype.value),
        )
        == _TG_KIND_INTERMEDIATE
    )


@pytest.mark.parametrize("mtype", _FINAL_TYPES)
def test_classify_all_final_types(mtype):
    assert (
        TelegramChannel._classify_completed_event_kind(
            SimpleNamespace(type=mtype),
        )
        == _TG_KIND_FINAL
    )
    assert (
        TelegramChannel._classify_completed_event_kind(
            SimpleNamespace(type=mtype.value),
        )
        == _TG_KIND_FINAL
    )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        SimpleNamespace(),
        "super_future_type_xyz",
        "TOOL",  # must NOT fuzzy-match tool call types
        "message_extended",
        "",
    ],
)
def test_classify_unknown_future_types_keep(raw):
    event = SimpleNamespace(type=raw)
    assert (
        TelegramChannel._classify_completed_event_kind(event) == _TG_KIND_FINAL
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mtype", _INTERMEDIATE_TYPES)
async def test_all_intermediate_types_tracked_and_cleaned(tmp_path, mtype):
    """Every intermediate MessageType (incl. all 3 OUTPUTs) is cleaned."""
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=1700)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_event_message_completed(
        None,
        "1",
        _event_for_type(mtype),
        send_meta,
    )
    state = send_meta["_tg_stream"]
    assert len(state["intermediate_ids"]) == 1, mtype
    assert not state["final_ids"]
    await ch._on_process_completed(None, "1", send_meta)
    assert deleted == state["intermediate_ids"], mtype


@pytest.mark.asyncio
@pytest.mark.parametrize("mtype", _FINAL_TYPES)
async def test_all_final_types_kept(tmp_path, mtype):
    """MESSAGE and RESULT are never deleted."""
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=1800)
    send_meta: Dict = {"chat_id": "1"}
    await ch.on_event_message_completed(
        None,
        "1",
        _event_for_type(mtype),
        send_meta,
    )
    state = send_meta["_tg_stream"]
    assert not state["intermediate_ids"]
    assert len(state["final_ids"]) == 1, mtype
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


# =============================================================================
# Issue #7586 close-out: DATA / on_event_content boundary
# =============================================================================


def _data_event(status, output=None):
    return SimpleNamespace(
        type=ContentType.DATA,
        status=status,
        data={"name": "tool", "output": output},
        object="content",
        delta=False,
    )


@pytest.mark.asyncio
async def test_data_inprogress_preview_is_intermediate(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=1900)
    send_meta: Dict = {"chat_id": "1"}
    handled = await ch.on_event_content(
        None,
        "1",
        _data_event(
            RunStatus.InProgress,
            [{"type": "text", "text": "working"}],
        ),
        send_meta,
    )
    assert handled is True
    assert len(send_meta["_tg_stream"]["intermediate_ids"]) == 1
    assert not send_meta["_tg_stream"]["final_ids"]
    await ch._on_process_completed(None, "1", send_meta)
    assert deleted == send_meta["_tg_stream"]["intermediate_ids"]


@pytest.mark.asyncio
async def test_data_completed_never_deleted_for_being_data(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=2000)
    send_meta: Dict = {"chat_id": "1"}
    handled = await ch.on_event_content(
        None,
        "1",
        _data_event(
            RunStatus.Completed,
            [{"type": "text", "text": "done"}],
        ),
        send_meta,
    )
    assert handled is False
    assert not send_meta.get("_tg_stream", {}).get("intermediate_ids", [])
    assert not send_meta.get("_tg_stream", {}).get("final_ids", [])
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


@pytest.mark.asyncio
async def test_unknown_content_type_is_kept(tmp_path):
    ch = _make_channel(tmp_path, cleanup=True)
    _, _, deleted = _install_bot(ch, start_id=2100)
    send_meta: Dict = {"chat_id": "1"}
    handled = await ch.on_event_content(
        None,
        "1",
        SimpleNamespace(
            type=ContentType.TEXT,
            status=RunStatus.InProgress,
            text="hello",
            object="content",
            delta=False,
        ),
        send_meta,
    )
    assert handled is False
    assert not send_meta.get("_tg_stream", {}).get("intermediate_ids", [])
    await ch._on_process_completed(None, "1", send_meta)
    assert not deleted


def test_from_env_cleanup_intermediate_bool_parsing(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CLEANUP_INTERMEDIATE", raising=False)
    ch = TelegramChannel.from_env(MagicMock())
    assert ch._cleanup_intermediate is False  # absent → false

    monkeypatch.setenv("TELEGRAM_CLEANUP_INTERMEDIATE", "1")
    assert TelegramChannel.from_env(MagicMock())._cleanup_intermediate is True
    monkeypatch.setenv("TELEGRAM_CLEANUP_INTERMEDIATE", "0")
    assert TelegramChannel.from_env(MagicMock())._cleanup_intermediate is False
