# -*- coding: utf-8 -*-

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    FileContent,
    VideoContent,
)
from copaw.app.channels.telegram.channel import (
    TELEGRAM_MAX_FILE_SIZE_BYTES,
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

    fake_stat = MagicMock()
    fake_stat.st_size = 1024  # small file, well under the 50 MB limit

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
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


@pytest.mark.asyncio
async def test_send_media_file_too_large_sends_error_message() -> None:
    """When a local file exceeds TELEGRAM_MAX_FILE_SIZE_BYTES, send_media
    notifies the user with a message that includes the file name and size."""
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(
        send_document=AsyncMock(),
        send_message=AsyncMock(),
    )
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///tmp/bigfile.mp4",
    )

    oversized = TELEGRAM_MAX_FILE_SIZE_BYTES + 1
    fake_stat = MagicMock()
    fake_stat.st_size = oversized

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    # The oversized file must NOT be uploaded
    bot.send_document.assert_not_called()
    # An error message must be sent back to the user
    bot.send_message.assert_called_once()
    error_text = bot.send_message.await_args.kwargs["text"]
    assert "bigfile.mp4" in error_text
    assert "50 MB" in error_text


@pytest.mark.asyncio
async def test_send_media_timed_out_sends_error_message() -> None:
    """When Telegram raises TimedOut, send_media notifies the user."""
    from telegram.error import TimedOut as TelegramTimedOut

    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(
        send_video=AsyncMock(side_effect=TelegramTimedOut()),
        send_message=AsyncMock(),
    )
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = VideoContent(
        type=ContentType.VIDEO,
        video_url="file:///tmp/video.mp4",
    )

    small_size = 1024  # well under the limit
    fake_stat = MagicMock()
    fake_stat.st_size = small_size

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
        patch("builtins.open", mock_open(read_data=b"data")),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    # An error message must be sent back to the user
    bot.send_message.assert_called_once()
    error_text = bot.send_message.await_args.kwargs["text"]
    assert "timed out" in error_text.lower()
    assert "50 MB" in error_text


@pytest.mark.asyncio
async def test_send_media_bad_request_sends_error_message() -> None:
    """When Telegram raises BadRequest, send_media notifies the user."""
    from telegram.error import BadRequest as TelegramBadRequest

    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(
        send_document=AsyncMock(
            side_effect=TelegramBadRequest("DOCUMENT_INVALID_DIMENSIONS"),
        ),
        send_message=AsyncMock(),
    )
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///tmp/bad.bin",
    )

    fake_stat = MagicMock()
    fake_stat.st_size = 1024

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
        patch("builtins.open", mock_open(read_data=b"data")),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    bot.send_message.assert_called_once()
    error_text = bot.send_message.await_args.kwargs["text"]
    assert "rejected" in error_text.lower()


@pytest.mark.asyncio
async def test_send_media_forbidden_sends_error_message() -> None:
    """When Telegram raises Forbidden, send_media notifies the user."""
    from telegram.error import Forbidden as TelegramForbidden

    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(
        send_document=AsyncMock(
            side_effect=TelegramForbidden("Bot was blocked by the user"),
        ),
        send_message=AsyncMock(),
    )
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///tmp/doc.pdf",
    )

    fake_stat = MagicMock()
    fake_stat.st_size = 1024

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
        patch("builtins.open", mock_open(read_data=b"data")),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    bot.send_message.assert_called_once()
    error_text = bot.send_message.await_args.kwargs["text"]
    assert "permission" in error_text.lower()


@pytest.mark.asyncio
async def test_send_media_network_error_sends_error_message() -> None:
    """When Telegram raises a NetworkError, send_media notifies the user."""
    from telegram.error import NetworkError as TelegramNetworkError

    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(
        send_document=AsyncMock(
            side_effect=TelegramNetworkError("Connection reset"),
        ),
        send_message=AsyncMock(),
    )
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///tmp/doc.pdf",
    )

    fake_stat = MagicMock()
    fake_stat.st_size = 1024

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
        patch("builtins.open", mock_open(read_data=b"data")),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    bot.send_message.assert_called_once()
    error_text = bot.send_message.await_args.kwargs["text"]
    assert "network" in error_text.lower()


@pytest.mark.asyncio
async def test_send_media_os_error_sends_error_message() -> None:
    """When a file can't be read (OSError), send_media notifies the user."""
    channel = TelegramChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
        media_dir="/tmp",
    )
    bot = SimpleNamespace(
        send_document=AsyncMock(),
        send_message=AsyncMock(),
    )
    # pylint: disable=protected-access
    channel._application = cast(Any, SimpleNamespace(bot=bot))
    part = FileContent(
        type=ContentType.FILE,
        file_url="file:///tmp/locked.pdf",
    )

    fake_stat = MagicMock()
    fake_stat.st_size = 1024

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=fake_stat),
        patch("builtins.open", side_effect=OSError("Permission denied")),
    ):
        await channel.send_media(
            "chat-1",
            part,
            meta={"chat_id": "chat-1"},
        )

    # The file was never uploaded
    bot.send_document.assert_not_called()
    # An error message must be sent back to the user
    bot.send_message.assert_called_once()
    error_text = bot.send_message.await_args.kwargs["text"]
    assert "failed" in error_text.lower()
