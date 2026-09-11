# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for Telegram Rich Messages table delivery and fallback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest, EndPointNotFound

from qwenpaw.app.channels.telegram.channel import TelegramChannel
from qwenpaw.app.channels.telegram.format_html import (
    has_markdown_table,
    markdown_table_column_count,
    markdown_to_telegram_html,
)


TABLE = "| A | B |\n|---|---|\n| 1 | 2 |"


def _channel(bot: MagicMock) -> TelegramChannel:
    """Build a channel with a minimal application for send tests."""
    channel = object.__new__(TelegramChannel)
    channel.enabled = True
    channel._application = SimpleNamespace(bot=bot)
    channel._is_processing = {}
    channel._stop_typing = MagicMock()
    channel._start_typing = MagicMock()
    return channel


def test_table_detection_ignores_fenced_code() -> None:
    """A table-looking fenced code block must use the legacy path."""
    assert has_markdown_table(TABLE)
    assert not has_markdown_table(f"```\n{TABLE}\n```")
    assert markdown_table_column_count(TABLE) == 2


def test_legacy_table_fallback_is_compact_and_escaped() -> None:
    """Legacy HTML output must avoid width-induced message inflation."""
    text = "| A | B |\n|---|---|\n| `<tag>` | **A & B** |"

    output = markdown_to_telegram_html(text)

    assert output.startswith("<pre>")
    assert "|---|---|" not in output
    assert "&lt;tag&gt;" in output
    assert "A &amp; B" in output
    assert "&amp;lt;" not in output
    assert "**A" not in output


@pytest.mark.asyncio
async def test_send_rich_message_payload_and_thread() -> None:
    """Table messages use the Rich API with the original Markdown."""
    bot = MagicMock()
    bot.do_api_request = AsyncMock(return_value={"ok": True})
    bot.send_message = AsyncMock()
    channel = _channel(bot)

    await channel.send("chat", TABLE, {"message_thread_id": 42})

    bot.do_api_request.assert_awaited_once_with(
        "sendRichMessage",
        api_kwargs={
            "chat_id": "chat",
            "message_thread_id": 42,
            "rich_message": {"markdown": TABLE},
        },
    )
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [BadRequest("unsupported"), EndPointNotFound("unsupported")],
)
async def test_send_falls_back_when_rich_api_is_unavailable(error) -> None:
    """Unsupported Rich API responses use the legacy sender."""
    bot = MagicMock()
    bot.do_api_request = AsyncMock(side_effect=error)
    bot.send_message = AsyncMock()
    channel = _channel(bot)

    await channel.send("chat", TABLE)

    bot.do_api_request.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    assert "<pre>" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_non_table_message_does_not_call_rich_api() -> None:
    """Ordinary messages retain the existing HTML send path."""
    bot = MagicMock()
    bot.do_api_request = AsyncMock()
    bot.send_message = AsyncMock()
    channel = _channel(bot)

    await channel.send("chat", "**bold**")

    bot.do_api_request.assert_not_awaited()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_table_over_rich_limit_uses_legacy_path() -> None:
    """Messages above the Rich limit do not make an invalid API request."""
    bot = MagicMock()
    bot.do_api_request = AsyncMock()
    bot.send_message = AsyncMock()
    channel = _channel(bot)
    text = TABLE + "x" * 32768

    await channel.send("chat", text)

    bot.do_api_request.assert_not_awaited()
    assert bot.send_message.await_count > 1


@pytest.mark.asyncio
async def test_rich_network_error_does_not_duplicate_send() -> None:
    """An uncertain Rich request must not be retried through sendMessage."""
    bot = MagicMock()
    bot.do_api_request = AsyncMock(side_effect=RuntimeError("timeout"))
    bot.send_message = AsyncMock()
    channel = _channel(bot)

    await channel.send("chat", TABLE)

    bot.do_api_request.assert_awaited_once()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_table_uses_rich_message_edit() -> None:
    """Streaming table completion edits the placeholder as Rich content."""
    bot = MagicMock()
    bot.do_api_request = AsyncMock(return_value={"ok": True})
    bot.edit_message_text = AsyncMock()
    channel = _channel(bot)
    send_meta = {
        "_tg_stream": {"message_ids": {"message": 99}},
    }

    await channel.on_streaming_end(
        None,
        "chat",
        None,
        send_meta,
        "message",
        TABLE,
    )

    bot.do_api_request.assert_awaited_once_with(
        "editMessageText",
        api_kwargs={
            "chat_id": "chat",
            "message_id": 99,
            "rich_message": {"markdown": TABLE},
        },
    )
    bot.edit_message_text.assert_not_awaited()
