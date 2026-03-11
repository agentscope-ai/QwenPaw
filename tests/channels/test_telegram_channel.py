# -*- coding: utf-8 -*-

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    FileContent,
)
from copaw.app.channels.telegram.channel import (
    TelegramChannel,
    _build_content_parts_from_message,
    _message_meta,
)


@pytest.mark.asyncio
async def test_build_content_parts_wraps_media_in_file_url() -> None:
    message = SimpleNamespace(
        text="hello",
        caption=None,
        entities=[],
        caption_entities=[],
        photo=[SimpleNamespace(file_id="photo-id")],
        document=SimpleNamespace(file_id="doc-id", file_name="doc.txt"),
        video=None,
        voice=None,
        audio=None,
    )
    update = SimpleNamespace(message=message, edited_message=None)

    with patch(
        "copaw.app.channels.telegram.channel._download_telegram_file",
        new=AsyncMock(side_effect=["/tmp/photo.jpg", "/tmp/doc.txt"]),
    ):
        parts, has_bot_command = await _build_content_parts_from_message(
            update,
            bot=MagicMock(),
            media_dir=Path("/tmp"),
        )

    assert has_bot_command is False
    assert parts[1].type == ContentType.IMAGE
    assert parts[1].image_url == "file:///tmp/photo.jpg"
    assert parts[2].type == ContentType.FILE
    assert parts[2].file_url == "file:///tmp/doc.txt"


@pytest.mark.asyncio
async def test_build_content_parts_ignores_non_content_message() -> None:
    message = SimpleNamespace(
        text=None,
        caption=None,
        entities=[],
        caption_entities=[],
        photo=None,
        document=None,
        video=None,
        voice=None,
        audio=None,
        new_chat_members=[SimpleNamespace(id=1)],
    )
    update = SimpleNamespace(message=message, edited_message=None)

    parts, has_bot_command = await _build_content_parts_from_message(
        update,
        bot=MagicMock(),
        media_dir=Path("/tmp"),
    )

    assert parts == []
    assert has_bot_command is False


def test_message_meta_includes_message_thread_id() -> None:
    update = SimpleNamespace(
        message=SimpleNamespace(
            chat=SimpleNamespace(id=123, type="supergroup"),
            from_user=SimpleNamespace(id=456, username="tester"),
            message_id=789,
            message_thread_id=42,
        ),
        edited_message=None,
    )

    meta = _message_meta(update)

    assert meta["chat_id"] == "123"
    assert meta["message_thread_id"] == 42


def test_apply_no_text_debounce_processes_media_only_message() -> None:
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
    )
    parts = [
        FileContent(
            type=ContentType.FILE,
            file_url="file:///tmp/demo.txt",
        ),
    ]

    # pylint: disable=protected-access
    should_process, merged = channel._apply_no_text_debounce(
        "telegram:123",
        parts,
    )

    assert should_process is True
    assert merged == parts


@pytest.mark.asyncio
async def test_send_uses_message_thread_id_for_text_reply() -> None:
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))

    await channel.send(
        "chat-1",
        "hello",
        meta={"chat_id": "chat-1", "message_thread_id": 7},
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == "chat-1"
    assert kwargs["message_thread_id"] == 7


@pytest.mark.asyncio
async def test_send_media_uses_message_thread_id_for_file_url() -> None:
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(send_document=AsyncMock())
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///tmp/demo.txt",
    )

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=b"demo")),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1", "message_thread_id": 9},
        )

    kwargs = bot.send_document.await_args.kwargs
    assert kwargs["chat_id"] == "chat-1"
    assert kwargs["message_thread_id"] == 9
    assert hasattr(kwargs["document"], "read")


@pytest.mark.asyncio
async def test_send_strips_html_in_plain_text_fallback() -> None:
    """On BadRequest, the fallback message has HTML tags stripped."""
    from telegram.error import BadRequest as TelegramBadRequest

    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
    )
    send_message = AsyncMock(
        side_effect=[TelegramBadRequest("can't parse entities"), None],
    )
    bot = SimpleNamespace(send_message=send_message)
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))

    await channel.send(
        "chat-1",
        "**hello**",
        meta={"chat_id": "chat-1"},
    )

    assert send_message.call_count == 2
    fallback_kwargs = send_message.call_args_list[1].kwargs
    assert "<" not in fallback_kwargs["text"]
    assert ">" not in fallback_kwargs["text"]
    # HTML entities produced by markdown_to_telegram_html should be unescaped
    assert "&lt;" not in fallback_kwargs["text"]
    assert "&gt;" not in fallback_kwargs["text"]
    assert "&amp;" not in fallback_kwargs["text"]


@pytest.mark.asyncio
async def test_send_media_warns_for_path_outside_media_dir() -> None:
    """file:// paths outside media_dir emit a warning but are still sent."""
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp/media",
    )
    bot = SimpleNamespace(send_document=AsyncMock())
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///etc/passwd",
    )

    with patch(
        "copaw.app.channels.telegram.channel.logger",
    ) as mock_logger:
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    warning_messages = [
        str(call) for call in mock_logger.warning.call_args_list
    ]
    assert any("outside allowed directory" in msg for msg in warning_messages)
    bot.send_document.assert_called_once()


@pytest.mark.asyncio
async def test_send_includes_thread_id_zero() -> None:
    """message_thread_id=0 (falsy but not None) must still be forwarded."""
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))

    await channel.send(
        "chat-1",
        "hello",
        meta={"chat_id": "chat-1", "message_thread_id": 0},
    )

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["message_thread_id"] == 0
