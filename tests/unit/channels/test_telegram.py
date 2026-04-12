# -*- coding: utf-8 -*-
"""
Telegram Channel Unit Tests

Comprehensive unit tests for TelegramChannel covering:
- Initialization and configuration
- Factory methods (from_env, from_config)
- Message chunking and formatting
- Typing indicators
- Send methods (text and media)
- Session resolution and routing
- File download and handling
- Media sending with error handling

Test Patterns:
- Uses tmp_path fixture for temporary files
- Uses AsyncMock for async method mocking
- Only uses @pytest.mark.asyncio on async test methods (no global pytestmark)

Run:
    pytest tests/unit/channels/test_telegram.py -v
    pytest tests/unit/channels/test_telegram.py::TestTelegramChannelInit -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=broad-exception-raised,using-constant-test
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process_handler() -> AsyncMock:
    """Mock process handler that yields simple events."""

    async def mock_process(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_process)


@pytest.fixture
def telegram_channel(
    mock_process_handler,
    tmp_path: Path,
) -> Generator:
    """Create a TelegramChannel instance for testing."""
    from copaw.app.channels.telegram.channel import TelegramChannel

    channel = TelegramChannel(
        process=mock_process_handler,
        enabled=True,
        bot_token="test_bot_token_12345",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="[TestBot] ",
        on_reply_sent=None,
        show_tool_details=True,
        media_dir=str(tmp_path / "media"),
        workspace_dir=tmp_path / "workspace",
        show_typing=True,
        filter_tool_messages=False,
        filter_thinking=False,
        dm_policy="open",
        group_policy="open",
        allow_from=None,
        deny_message="",
        require_mention=False,
    )
    yield channel


@pytest.fixture
def disabled_telegram_channel(
    mock_process_handler,
    tmp_path: Path,
) -> Generator:
    """Create a disabled TelegramChannel instance."""
    from copaw.app.channels.telegram.channel import TelegramChannel

    channel = TelegramChannel(
        process=mock_process_handler,
        enabled=False,
        bot_token="",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
    )
    yield channel


@pytest.fixture
def mock_telegram_bot() -> MagicMock:
    """Create a mock Telegram bot."""
    bot = MagicMock()
    bot.username = "test_bot"
    bot.id = 123456789
    bot.send_message = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_audio = AsyncMock()
    bot.send_document = AsyncMock()
    return bot


@pytest.fixture
def mock_telegram_file() -> MagicMock:
    """Create a mock Telegram file."""
    tg_file = MagicMock()
    tg_file.file_path = "photos/test_file.jpg"
    tg_file.download_to_drive = AsyncMock()
    return tg_file


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestTelegramChannelInit:
    """
    Tests for TelegramChannel initialization.
    Verifies correct storage of configuration parameters.
    """

    def test_init_stores_basic_config(
        self,
        mock_process_handler,
        tmp_path: Path,
    ):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        channel = TelegramChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token="my_bot_token",
            http_proxy="http://proxy.example.com:8080",
            http_proxy_auth="user:pass",
            bot_prefix="[MyBot] ",
            media_dir=str(tmp_path / "custom_media"),
            show_typing=False,
        )

        assert channel.enabled is True
        assert channel._bot_token == "my_bot_token"
        assert channel._http_proxy == "http://proxy.example.com:8080"
        assert channel._http_proxy_auth == "user:pass"
        assert channel.bot_prefix == "[MyBot] "
        assert channel._show_typing is False
        assert channel.channel == "telegram"

    def test_init_stores_policy_config(
        self,
        mock_process_handler,
        tmp_path: Path,
    ):
        """Constructor should store policy configuration."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        channel = TelegramChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token="token",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="",
            dm_policy="restricted",
            group_policy="restricted",
            allow_from=["user1", "user2"],
            deny_message="Access denied",
            require_mention=True,
        )

        assert channel.dm_policy == "restricted"
        assert channel.group_policy == "restricted"
        assert channel.allow_from == {"user1", "user2"}
        assert channel.deny_message == "Access denied"
        assert channel.require_mention is True

    def test_init_creates_internal_data_structures(
        self,
        mock_process_handler,
    ):
        """Constructor should initialize required internal data structures."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        channel = TelegramChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token="token",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="",
        )

        # Typing tasks dict
        assert hasattr(channel, "_typing_tasks")
        assert isinstance(channel._typing_tasks, dict)
        assert len(channel._typing_tasks) == 0

        # Task placeholder
        assert hasattr(channel, "_task")
        assert channel._task is None

        # Application placeholder
        assert hasattr(channel, "_application")

    def test_channel_type_is_telegram(self, telegram_channel):
        """Channel type must be 'telegram'."""
        assert telegram_channel.channel == "telegram"

    def test_init_disabled_without_token(
        self,
        mock_process_handler,
        caplog,
    ):
        """Channel should log info when enabled but token is empty."""
        import logging
        from copaw.app.channels.telegram.channel import TelegramChannel

        with caplog.at_level(logging.INFO):
            channel = TelegramChannel(
                process=mock_process_handler,
                enabled=True,
                bot_token="",
                http_proxy="",
                http_proxy_auth="",
                bot_prefix="",
            )

        assert channel.enabled is True
        # Check that channel was created successfully
        assert channel.channel == "telegram"
        assert channel._bot_token == ""

    def test_uses_manager_queue_is_true(self, telegram_channel):
        """uses_manager_queue should be True for queue-based processing."""
        assert telegram_channel.uses_manager_queue is True


# =============================================================================
# P0: Factory Methods
# =============================================================================


class TestTelegramChannelFromEnv:
    """Tests for from_env factory method."""

    def test_from_env_reads_basic_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read basic environment variables."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        monkeypatch.setenv("TELEGRAM_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_bot_token")
        monkeypatch.setenv("TELEGRAM_HTTP_PROXY", "http://env.proxy:8080")
        monkeypatch.setenv("TELEGRAM_HTTP_PROXY_AUTH", "env_user:env_pass")
        monkeypatch.setenv("TELEGRAM_BOT_PREFIX", "[EnvBot] ")
        monkeypatch.setenv("TELEGRAM_SHOW_TYPING", "0")

        channel = TelegramChannel.from_env(mock_process_handler)

        assert channel.enabled is True
        assert channel._bot_token == "env_bot_token"
        assert channel._http_proxy == "http://env.proxy:8080"
        assert channel._http_proxy_auth == "env_user:env_pass"
        assert channel.bot_prefix == "[EnvBot] "
        assert channel._show_typing is False

    def test_from_env_reads_policy_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read policy environment variables."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("TELEGRAM_DM_POLICY", "restricted")
        monkeypatch.setenv("TELEGRAM_GROUP_POLICY", "restricted")
        monkeypatch.setenv("TELEGRAM_ALLOW_FROM", "user1,user2,user3")
        monkeypatch.setenv("TELEGRAM_DENY_MESSAGE", "Custom deny message")
        monkeypatch.setenv("TELEGRAM_REQUIRE_MENTION", "1")

        channel = TelegramChannel.from_env(mock_process_handler)

        assert channel.dm_policy == "restricted"
        assert channel.group_policy == "restricted"
        assert channel.allow_from == {"user1", "user2", "user3"}
        assert channel.deny_message == "Custom deny message"
        assert channel.require_mention is True

    def test_from_env_allow_from_parsing(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should parse TELEGRAM_ALLOW_FROM with whitespace."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("TELEGRAM_ALLOW_FROM", " user1 , user2 , user3 ")

        channel = TelegramChannel.from_env(mock_process_handler)

        assert "user1" in channel.allow_from
        assert "user2" in channel.allow_from
        assert "user3" in channel.allow_from

    def test_from_env_empty_allow_from(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should handle empty TELEGRAM_ALLOW_FROM."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setenv("TELEGRAM_ALLOW_FROM", "")

        channel = TelegramChannel.from_env(mock_process_handler)

        assert channel.allow_from == set()

    def test_from_env_defaults(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should use sensible defaults."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.delenv("TELEGRAM_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("TELEGRAM_SHOW_TYPING", raising=False)
        monkeypatch.delenv("TELEGRAM_DM_POLICY", raising=False)

        channel = TelegramChannel.from_env(mock_process_handler)

        assert channel.enabled is False  # Default disabled
        assert channel._show_typing is True  # Default True
        assert channel.dm_policy == "open"  # Default open


class TestTelegramChannelFromConfig:
    """Tests for from_config factory method."""

    def test_from_config_uses_config_values(
        self,
        mock_process_handler,
    ):
        """from_config should use values from config dict."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        config = {
            "enabled": True,
            "bot_token": "config_token",
            "http_proxy": "http://config.proxy:8080",
            "http_proxy_auth": "config_user:config_pass",
            "bot_prefix": "[ConfigBot] ",
            "show_typing": False,
            "dm_policy": "restricted",
            "group_policy": "restricted",
            "allow_from": ["user1", "user2"],
            "deny_message": "Config deny message",
            "require_mention": True,
        }

        channel = TelegramChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is True
        assert channel._bot_token == "config_token"
        assert channel._http_proxy == "http://config.proxy:8080"
        assert channel._http_proxy_auth == "config_user:config_pass"
        assert channel.bot_prefix == "[ConfigBot]"
        assert channel._show_typing is False
        assert channel.dm_policy == "restricted"
        assert channel.group_policy == "restricted"
        assert channel.allow_from == {"user1", "user2"}
        assert channel.deny_message == "Config deny message"
        assert channel.require_mention is True

    def test_from_config_with_config_object(
        self,
        mock_process_handler,
    ):
        """from_config should work with TelegramConfig object."""
        from copaw.app.channels.telegram.channel import TelegramChannel
        from copaw.config.config import TelegramConfig

        config = TelegramConfig(
            enabled=True,
            bot_token="obj_token",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="[Obj] ",
        )

        channel = TelegramChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel._bot_token == "obj_token"
        assert channel.bot_prefix == "[Obj]"

    def test_from_config_defaults(
        self,
        mock_process_handler,
    ):
        """from_config should use defaults for missing values."""
        from copaw.app.channels.telegram.channel import TelegramChannel

        config = {
            "bot_token": "token_only",
        }

        channel = TelegramChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is False  # Default
        assert channel.dm_policy == "open"  # Default
        assert channel.group_policy == "open"  # Default
        assert channel.require_mention is False  # Default


# =============================================================================
# P1: Text Chunking
# =============================================================================


class TestTelegramChunkText:
    """Tests for _chunk_text method."""

    def test_chunk_text_empty(self, telegram_channel):
        """Empty text should return empty list."""
        result = telegram_channel._chunk_text("")
        assert result == []

    def test_chunk_text_short(self, telegram_channel):
        """Short text should return single chunk."""
        text = "Hello world"
        result = telegram_channel._chunk_text(text)
        assert result == ["Hello world"]

    def test_chunk_text_exact_size(self, telegram_channel):
        """Text at exactly chunk size should return single chunk."""
        text = "A" * 4000
        result = telegram_channel._chunk_text(text)
        assert len(result) == 1
        assert len(result[0]) == 4000

    def test_chunk_text_long_splits(self, telegram_channel):
        """Long text should be split into chunks."""
        text = "A" * 5000
        result = telegram_channel._chunk_text(text)
        assert len(result) > 1
        assert all(len(chunk) <= 4000 for chunk in result)

    def test_chunk_text_respects_newlines(self, telegram_channel):
        """Split should prefer newline boundaries."""
        text = "Line 1\n" * 1000  # Many lines
        result = telegram_channel._chunk_text(text)
        # Each chunk should be at chunk size or less
        assert all(len(chunk) <= 4000 for chunk in result)

    def test_chunk_text_respects_spaces(self, telegram_channel):
        """Split should fallback to space boundaries."""
        text = "word " * 2000  # Many words, no newlines
        result = telegram_channel._chunk_text(text)
        assert all(len(chunk) <= 4000 for chunk in result)
        # First chunk should end with space
        assert result[0].endswith(" ")

    def test_chunk_text_no_good_boundary(self, telegram_channel):
        """Long word without spaces should be hard split."""
        text = "A" * 5000  # Single long word
        result = telegram_channel._chunk_text(text)
        assert len(result) > 1
        assert all(len(chunk) <= 4000 for chunk in result)


# =============================================================================
# P1: Typing Indicators
# =============================================================================


@pytest.mark.asyncio
class TestTelegramTypingIndicators:
    """Tests for typing indicator methods."""

    async def test_send_chat_action_disabled_channel(
        self,
        disabled_telegram_channel,
    ):
        """send_chat_action should return early when disabled."""
        await disabled_telegram_channel._send_chat_action("12345", "typing")
        # Should not raise

    async def test_send_chat_action_no_application(self, telegram_channel):
        """send_chat_action should return early when no application."""
        telegram_channel._application = None
        await telegram_channel._send_chat_action("12345", "typing")
        # Should not raise

    async def test_send_chat_action_success(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send_chat_action should send chat action via bot."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        await telegram_channel._send_chat_action("12345", "typing")

        mock_telegram_bot.send_chat_action.assert_called_once_with(
            chat_id="12345",
            action="typing",
        )

    async def test_send_chat_action_handles_exception(self, telegram_channel):
        """send_chat_action should handle exceptions gracefully."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = MagicMock()
        telegram_channel._application.bot.send_chat_action = AsyncMock(
            side_effect=Exception("Network error"),
        )

        # Should not raise
        await telegram_channel._send_chat_action("12345", "typing")

    def test_start_typing_creates_task(self, telegram_channel):
        """_start_typing should create typing task."""
        telegram_channel._show_typing = True
        telegram_channel._application = MagicMock()

        with patch("asyncio.create_task") as mock_create_task:
            mock_task = MagicMock()
            mock_create_task.return_value = mock_task

            telegram_channel._start_typing("12345")

            assert "12345" in telegram_channel._typing_tasks
            mock_create_task.assert_called_once()

    def test_start_typing_disabled(self, telegram_channel):
        """_start_typing should do nothing when show_typing is False."""
        telegram_channel._show_typing = False

        with patch("asyncio.create_task") as mock_create_task:
            telegram_channel._start_typing("12345")
            mock_create_task.assert_not_called()

    def test_start_typing_replaces_existing(self, telegram_channel):
        """_start_typing should replace existing typing task."""
        telegram_channel._show_typing = True
        old_task = MagicMock()
        old_task.done.return_value = False
        telegram_channel._typing_tasks["12345"] = old_task

        with patch("asyncio.create_task") as mock_create_task:
            new_task = MagicMock()
            mock_create_task.return_value = new_task

            telegram_channel._start_typing("12345")

            old_task.cancel.assert_called_once()
            assert telegram_channel._typing_tasks["12345"] is new_task

    def test_stop_typing_cancels_task(self, telegram_channel):
        """_stop_typing should cancel typing task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        telegram_channel._typing_tasks["12345"] = mock_task

        telegram_channel._stop_typing("12345")

        mock_task.cancel.assert_called_once()
        assert "12345" not in telegram_channel._typing_tasks

    def test_stop_typing_no_task(self, telegram_channel):
        """_stop_typing should handle missing task."""
        # Should not raise
        telegram_channel._stop_typing("99999")

    async def test_typing_loop_sends_typing(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """_typing_loop should send typing action periodically."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        # Mock current_task in typing_tasks
        task = asyncio.create_task(
            telegram_channel._typing_loop("12345"),
        )
        telegram_channel._typing_tasks["12345"] = task

        # Let it run briefly then cancel
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Bot should have been called with typing action
        mock_telegram_bot.send_chat_action.assert_called()


# =============================================================================
# P1: Send Messages
# =============================================================================


@pytest.mark.asyncio
class TestTelegramSend:
    """Tests for send method."""

    async def test_send_disabled_channel(self, disabled_telegram_channel):
        """send should return early when channel is disabled."""
        result = await disabled_telegram_channel.send("12345", "Hello", {})
        assert result is None

    async def test_send_no_application(self, telegram_channel):
        """send should return early when no application."""
        telegram_channel._application = None
        result = await telegram_channel.send("12345", "Hello", {})
        assert result is None

    async def test_send_no_chat_id(self, telegram_channel):
        """send should return early when no chat_id."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = MagicMock()

        result = await telegram_channel.send("", "Hello", {})
        assert result is None

        result = await telegram_channel.send("", "Hello", {"chat_id": ""})
        assert result is None

    async def test_send_success(self, telegram_channel, mock_telegram_bot):
        """send should send message via bot."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        await telegram_channel.send("12345", "Hello world", {})

        mock_telegram_bot.send_message.assert_called_once()
        call_kwargs = mock_telegram_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == "12345"
        assert "Hello world" in call_kwargs["text"]

    async def test_send_with_message_thread_id(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send should include message_thread_id when provided."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        await telegram_channel.send(
            "12345",
            "Hello",
            {"chat_id": "12345", "message_thread_id": 789},
        )

        call_kwargs = mock_telegram_bot.send_message.call_args.kwargs
        assert call_kwargs["message_thread_id"] == 789

    async def test_send_stops_typing(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send should stop typing indicator before sending."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        with patch.object(telegram_channel, "_stop_typing") as mock_stop:
            await telegram_channel.send("12345", "Hello", {})
            mock_stop.assert_called_once_with("12345")

    async def test_send_chunks_long_messages(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send should split long messages into chunks."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        long_text = "A" * 5000
        await telegram_channel.send("12345", long_text, {})

        # Should call multiple times for chunks
        assert mock_telegram_bot.send_message.call_count > 1

    async def test_send_handles_badrequest_fallback(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send should fallback to plain text on BadRequest."""
        from telegram.error import BadRequest

        telegram_channel._application = MagicMock()
        # First call raises BadRequest, second call succeeds
        mock_telegram_bot.send_message = AsyncMock(
            side_effect=[
                BadRequest("Can't parse HTML"),
                None,  # Second call succeeds
            ],
        )
        telegram_channel._application.bot = mock_telegram_bot

        # Text with markdown that might fail HTML parsing
        html_text = "<b>Bold</b> and <i>italic</i>"
        await telegram_channel.send("12345", html_text, {})

        # Should be called twice - first with HTML, second without
        assert mock_telegram_bot.send_message.call_count == 2

    async def test_send_handles_general_exception(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send should handle general exceptions."""
        telegram_channel._application = MagicMock()
        mock_telegram_bot.send_message = AsyncMock(
            side_effect=Exception("Error"),
        )
        telegram_channel._application.bot = mock_telegram_bot

        # Should not raise
        result = await telegram_channel.send("12345", "Hello", {})
        assert result is None


# =============================================================================
# P1: Send Media
# =============================================================================


@pytest.mark.asyncio
class TestTelegramSendMedia:
    """Tests for send_media method."""

    async def test_send_media_disabled_channel(
        self,
        disabled_telegram_channel,
    ):
        """send_media should return early when disabled."""
        part = MagicMock()
        part.type = ContentType.IMAGE
        result = await disabled_telegram_channel.send_media("12345", part, {})
        assert result is None

    async def test_send_media_no_application(self, telegram_channel):
        """send_media should return early when no application."""
        telegram_channel._application = None
        part = MagicMock()
        part.type = ContentType.IMAGE
        result = await telegram_channel.send_media("12345", part, {})
        assert result is None

    async def test_send_media_no_chat_id(self, telegram_channel):
        """send_media should return early when no chat_id."""
        telegram_channel._application = MagicMock()
        part = MagicMock()
        part.type = ContentType.IMAGE

        result = await telegram_channel.send_media("", part, {})
        assert result is None

    async def test_send_media_image(self, telegram_channel, mock_telegram_bot):
        """send_media should send image via send_photo."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://example.com/img.jpg",
        )
        await telegram_channel.send_media("12345", part, {})

        mock_telegram_bot.send_photo.assert_called_once()
        call_kwargs = mock_telegram_bot.send_photo.call_args.kwargs
        assert call_kwargs["chat_id"] == "12345"
        assert call_kwargs["photo"] == "http://example.com/img.jpg"

    async def test_send_media_video(self, telegram_channel, mock_telegram_bot):
        """send_media should send video via send_video."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        part = VideoContent(
            type=ContentType.VIDEO,
            video_url="http://example.com/video.mp4",
        )
        await telegram_channel.send_media("12345", part, {})

        mock_telegram_bot.send_video.assert_called_once()
        call_kwargs = mock_telegram_bot.send_video.call_args.kwargs
        assert call_kwargs["video"] == "http://example.com/video.mp4"

    async def test_send_media_audio(self, telegram_channel, mock_telegram_bot):
        """send_media should send audio via send_audio."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        part = AudioContent(type=ContentType.AUDIO, data=b"audio_data")
        await telegram_channel.send_media("12345", part, {})

        mock_telegram_bot.send_audio.assert_called_once()
        call_kwargs = mock_telegram_bot.send_audio.call_args.kwargs
        # Audio data may be bytes or string depending on implementation
        assert call_kwargs["audio"] in [b"audio_data", "audio_data"]

    async def test_send_media_file(self, telegram_channel, mock_telegram_bot):
        """send_media should send file via send_document."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        part = FileContent(
            type=ContentType.FILE,
            file_url="http://example.com/doc.pdf",
        )
        await telegram_channel.send_media("12345", part, {})

        mock_telegram_bot.send_document.assert_called_once()
        call_kwargs = mock_telegram_bot.send_document.call_args.kwargs
        assert call_kwargs["document"] == "http://example.com/doc.pdf"

    async def test_send_media_unknown_type(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send_media should handle unknown content type."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        part = MagicMock()
        part.type = "unknown_type"

        # Should complete without calling any send method
        await telegram_channel.send_media("12345", part, {})

        mock_telegram_bot.send_photo.assert_not_called()
        mock_telegram_bot.send_video.assert_not_called()
        mock_telegram_bot.send_audio.assert_not_called()
        mock_telegram_bot.send_document.assert_not_called()

    async def test_send_media_with_message_thread_id(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """send_media should include message_thread_id when provided."""
        telegram_channel._application = MagicMock()
        telegram_channel._application.bot = mock_telegram_bot

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://example.com/img.jpg",
        )
        await telegram_channel.send_media(
            "12345",
            part,
            {"message_thread_id": 789},
        )

        call_kwargs = mock_telegram_bot.send_photo.call_args.kwargs
        assert call_kwargs["message_thread_id"] == 789


# =============================================================================
# P1: Send Media Value (Local Files)
# =============================================================================


@pytest.mark.asyncio
class TestTelegramSendMediaValue:
    """Tests for _send_media_value with local files."""

    async def test_send_media_value_local_file_success(
        self,
        telegram_channel,
        mock_telegram_bot,
        tmp_path: Path,
    ):
        """Should send local file when file:// URL provided."""
        # Create a test file
        test_file = tmp_path / "test_image.jpg"
        test_file.write_bytes(b"fake_image_data")

        await telegram_channel._send_media_value(
            bot=mock_telegram_bot,
            chat_id="12345",
            value=f"file://{test_file}",
            method_name="send_photo",
            payload_name="photo",
            message_thread_id=None,
        )

        mock_telegram_bot.send_photo.assert_called_once()

    async def test_send_media_value_file_not_found(
        self,
        telegram_channel,
        mock_telegram_bot,
        tmp_path: Path,
    ):
        """Should raise _MediaFileUnavailableError when file not found."""
        from copaw.app.channels.telegram.channel import (
            _MediaFileUnavailableError,
        )

        nonexistent_file = tmp_path / "nonexistent.jpg"

        with pytest.raises(_MediaFileUnavailableError):
            await telegram_channel._send_media_value(
                bot=mock_telegram_bot,
                chat_id="12345",
                value=f"file://{nonexistent_file}",
                method_name="send_photo",
                payload_name="photo",
                message_thread_id=None,
            )

    async def test_send_media_value_file_too_large(
        self,
        telegram_channel,
        mock_telegram_bot,
        tmp_path: Path,
    ):
        """Should raise _FileTooLargeError when file exceeds limit."""
        from copaw.app.channels.telegram.channel import (
            _FileTooLargeError,
            TELEGRAM_MAX_FILE_SIZE_BYTES,
        )

        # Create a file larger than 50MB
        test_file = tmp_path / "large_file.bin"
        test_file.write_bytes(b"x" * (TELEGRAM_MAX_FILE_SIZE_BYTES + 1000))

        with pytest.raises(_FileTooLargeError):
            await telegram_channel._send_media_value(
                bot=mock_telegram_bot,
                chat_id="12345",
                value=f"file://{test_file}",
                method_name="send_document",
                payload_name="document",
                message_thread_id=None,
            )

    async def test_send_media_value_http_url(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """Should send HTTP URL directly without file handling."""
        await telegram_channel._send_media_value(
            bot=mock_telegram_bot,
            chat_id="12345",
            value="http://example.com/image.jpg",
            method_name="send_photo",
            payload_name="photo",
            message_thread_id=789,
        )

        mock_telegram_bot.send_photo.assert_called_once_with(
            chat_id="12345",
            photo="http://example.com/image.jpg",
            message_thread_id=789,
        )

    async def test_send_media_value_empty_value(
        self,
        telegram_channel,
        mock_telegram_bot,
    ):
        """Should return early when value is empty."""
        await telegram_channel._send_media_value(
            bot=mock_telegram_bot,
            chat_id="12345",
            value="",
            method_name="send_photo",
            payload_name="photo",
            message_thread_id=None,
        )

        mock_telegram_bot.send_photo.assert_not_called()


# =============================================================================
# P1: Session Resolution
# =============================================================================


class TestTelegramSessionResolution:
    """Tests for session resolution methods."""

    def test_resolve_session_id_with_chat_id(self, telegram_channel):
        """resolve_session_id should use chat_id when available."""
        result = telegram_channel.resolve_session_id(
            "user123",
            {"chat_id": "456"},
        )
        assert result == "telegram:456"

    def test_resolve_session_id_fallback_to_sender(self, telegram_channel):
        """resolve_session_id should fallback to sender_id when no chat_id."""
        result = telegram_channel.resolve_session_id(
            "user123",
            {},
        )
        assert result == "telegram:user123"

    def test_resolve_session_id_no_meta(self, telegram_channel):
        """resolve_session_id should handle None meta."""
        result = telegram_channel.resolve_session_id("user123", None)
        assert result == "telegram:user123"

    def test_to_handle_from_request_with_chat_id(self, telegram_channel):
        """get_to_handle_from_request should use chat_id from meta."""
        mock_request = MagicMock()
        mock_request.channel_meta = {"chat_id": "456"}
        mock_request.session_id = "telegram:789"

        result = telegram_channel.get_to_handle_from_request(mock_request)
        assert result == "456"

    def test_to_handle_from_request_with_session_id(self, telegram_channel):
        """get_to_handle_from_request should parse session_id."""
        mock_request = MagicMock()
        mock_request.channel_meta = {}
        mock_request.session_id = "telegram:789"
        mock_request.user_id = "user123"

        result = telegram_channel.get_to_handle_from_request(mock_request)
        assert result == "789"

    def test_to_handle_from_request_fallback_to_user_id(
        self,
        telegram_channel,
    ):
        """get_to_handle_from_request should fallback to user_id."""
        mock_request = MagicMock()
        mock_request.channel_meta = {}
        mock_request.session_id = "other:789"
        mock_request.user_id = "user123"

        result = telegram_channel.get_to_handle_from_request(mock_request)
        assert result == "user123"

    def test_to_handle_from_target_with_session_id(self, telegram_channel):
        """to_handle_from_target should parse telegram: session_id."""
        result = telegram_channel.to_handle_from_target(
            user_id="user123",
            session_id="telegram:456",
        )
        assert result == "456"

    def test_to_handle_from_target_fallback_to_user_id(self, telegram_channel):
        """to_handle_from_target should fallback to user_id."""
        result = telegram_channel.to_handle_from_target(
            user_id="user123",
            session_id="other:456",
        )
        assert result == "user123"


# =============================================================================
# P1: Build Agent Request
# =============================================================================


class TestTelegramBuildAgentRequest:
    """Tests for build_agent_request_from_native method."""

    def test_build_agent_request_with_full_payload(self, telegram_channel):
        """Should create AgentRequest from complete native payload."""
        payload = {
            "channel_id": "telegram",
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {"chat_id": "456", "user_id": "789"},
        }

        request = telegram_channel.build_agent_request_from_native(payload)

        assert request.user_id == "789"  # From meta
        assert request.channel == "telegram"
        assert len(request.input) == 1
        assert request.channel_meta == {"chat_id": "456", "user_id": "789"}

    def test_build_agent_request_defaults(self, telegram_channel):
        """Should use defaults for missing fields."""
        payload = {
            "sender_id": "user123",
            "content_parts": [],
        }

        request = telegram_channel.build_agent_request_from_native(payload)

        assert request.user_id == "user123"  # From sender_id
        assert request.channel == "telegram"  # Default channel


# =============================================================================
# P1: No Text Debounce
# =============================================================================


class TestTelegramNoTextDebounce:
    """Tests for _apply_no_text_debounce override."""

    def test_media_only_triggers_immediate_processing(
        self,
        telegram_channel,
    ):
        """Media-only content should trigger immediate processing."""
        parts = [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="http://example.com/img.jpg",
            ),
        ]

        should_process, merged = telegram_channel._apply_no_text_debounce(
            "session_1",
            parts,
        )

        assert should_process is True
        assert len(merged) == 1

    def test_text_content_uses_base_behavior(
        self,
        telegram_channel,
    ):
        """Text content should use base class debounce logic."""
        parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
        ]

        should_process, merged = telegram_channel._apply_no_text_debounce(
            "session_2",
            parts,
        )

        assert should_process is True
        assert len(merged) == 1


# =============================================================================
# P1: Module-Level File Download
# =============================================================================


@pytest.mark.asyncio
class TestTelegramDownloadFile:
    """Tests for _download_telegram_file function."""

    async def test_download_file_success(self, tmp_path: Path):
        """Should download file and return local path."""
        from copaw.app.channels.telegram.channel import _download_telegram_file

        mock_bot = MagicMock()
        mock_file = MagicMock()
        mock_file.file_path = "photos/test.jpg"
        mock_file.download_to_drive = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        result = await _download_telegram_file(
            bot=mock_bot,
            file_id="file123",
            media_dir=tmp_path,
            filename_hint="test.jpg",
        )

        assert result is not None
        assert tmp_path in Path(result).parents or str(tmp_path) in result
        mock_file.download_to_drive.assert_called_once()

    async def test_download_file_telegram_error(self, tmp_path: Path):
        """Should return None on TelegramError."""
        from copaw.app.channels.telegram.channel import _download_telegram_file
        from telegram.error import TelegramError

        mock_bot = MagicMock()
        mock_bot.get_file = AsyncMock(side_effect=TelegramError("Error"))

        result = await _download_telegram_file(
            bot=mock_bot,
            file_id="file123",
            media_dir=tmp_path,
        )

        assert result is None

    async def test_download_file_with_suffix_from_hint(self, tmp_path: Path):
        """Should use file suffix from filename_hint when not in file_path."""
        from copaw.app.channels.telegram.channel import _download_telegram_file

        mock_bot = MagicMock()
        mock_file = MagicMock()
        mock_file.file_path = "photos/file_no_ext"  # No suffix
        mock_file.download_to_drive = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        result = await _download_telegram_file(
            bot=mock_bot,
            file_id="file123",
            media_dir=tmp_path,
            filename_hint="image.png",
        )

        # Result should have .png suffix from hint
        assert result is not None
        assert result.endswith(".png")

    async def test_download_file_creates_directory(self, tmp_path: Path):
        """Should create media_dir if it doesn't exist."""
        from copaw.app.channels.telegram.channel import _download_telegram_file

        mock_bot = MagicMock()
        mock_file = MagicMock()
        mock_file.file_path = "test.jpg"
        mock_file.download_to_drive = AsyncMock()
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        nested_dir = tmp_path / "nested" / "media"
        assert not nested_dir.exists()

        result = await _download_telegram_file(
            bot=mock_bot,
            file_id="file123",
            media_dir=nested_dir,
        )

        assert nested_dir.exists()
        assert result is not None


@pytest.mark.asyncio
class TestTelegramResolveFileUrl:
    """Tests for _resolve_telegram_file_url function."""

    async def test_resolve_external_url(self):
        """Should return external URL as-is."""
        from copaw.app.channels.telegram.channel import (
            _resolve_telegram_file_url,
        )

        mock_bot = MagicMock()
        mock_file = MagicMock()
        mock_file.file_path = "http://external.server.com/file.jpg"
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        result = await _resolve_telegram_file_url(
            bot=mock_bot,
            file_id="file123",
            bot_token="test_token",
        )

        assert result == "http://external.server.com/file.jpg"

    async def test_resolve_api_url(self):
        """Should construct Telegram API URL for local file paths."""
        from copaw.app.channels.telegram.channel import (
            _resolve_telegram_file_url,
        )

        mock_bot = MagicMock()
        mock_file = MagicMock()
        mock_file.file_path = "photos/file_123.jpg"
        mock_bot.get_file = AsyncMock(return_value=mock_file)

        result = await _resolve_telegram_file_url(
            bot=mock_bot,
            file_id="file123",
            bot_token="my_bot_token",
        )

        expected = (
            "https://api.telegram.org/file/botmy_bot_token/photos/file_123.jpg"
        )
        assert result == expected

    async def test_resolve_error_returns_empty(self):
        """Should return empty string on TelegramError."""
        from copaw.app.channels.telegram.channel import (
            _resolve_telegram_file_url,
        )
        from telegram.error import TelegramError

        mock_bot = MagicMock()
        mock_bot.get_file = AsyncMock(side_effect=TelegramError("Error"))

        result = await _resolve_telegram_file_url(
            bot=mock_bot,
            file_id="file123",
            bot_token="test_token",
        )

        assert result == ""


# =============================================================================
# P1: Message Meta Extraction
# =============================================================================


class TestTelegramMessageMeta:
    """Tests for _message_meta function."""

    def test_message_meta_full(self):
        """Should extract all meta fields from update."""
        from copaw.app.channels.telegram.channel import _message_meta

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_chat = MagicMock()
        mock_user = MagicMock()

        mock_chat.id = 123456
        mock_chat.type = "group"
        mock_user.id = 789
        mock_user.username = "testuser"
        mock_message.chat = mock_chat
        mock_message.from_user = mock_user
        mock_message.message_id = 100
        mock_message.message_thread_id = 50

        mock_update.message = mock_message

        result = _message_meta(mock_update)

        assert result["chat_id"] == "123456"
        assert result["user_id"] == "789"
        assert result["username"] == "testuser"
        assert result["message_id"] == "100"
        assert result["is_group"] is True
        assert result["message_thread_id"] == 50

    def test_message_meta_edited_message(self):
        """Should handle edited_message."""
        from copaw.app.channels.telegram.channel import _message_meta

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_chat = MagicMock()
        mock_user = MagicMock()

        mock_chat.id = 123456
        mock_chat.type = "private"
        mock_user.id = 789
        mock_user.username = None
        mock_message.chat = mock_chat
        mock_message.from_user = mock_user
        mock_message.message_id = 100
        mock_message.message_thread_id = None

        mock_update.message = None
        mock_update.edited_message = mock_message

        result = _message_meta(mock_update)

        assert result["is_group"] is False
        assert result["username"] == ""

    def test_message_meta_no_message(self):
        """Should return empty dict when no message."""
        from copaw.app.channels.telegram.channel import _message_meta

        mock_update = MagicMock()
        mock_update.message = None
        mock_update.edited_message = None

        result = _message_meta(mock_update)

        assert not result

    def test_message_meta_supergroup_is_group(self):
        """Should treat supergroup as group."""
        from copaw.app.channels.telegram.channel import _message_meta

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_chat = MagicMock()
        mock_user = MagicMock()

        mock_chat.id = 123456
        mock_chat.type = "supergroup"
        mock_user.id = 789
        mock_message.chat = mock_chat
        mock_message.from_user = mock_user
        mock_message.message_id = 100
        mock_message.message_thread_id = None

        mock_update.message = mock_message

        result = _message_meta(mock_update)

        assert result["is_group"] is True


# =============================================================================
# P2: Build Content Parts from Message
# =============================================================================


@pytest.mark.asyncio
class TestTelegramBuildContentParts:
    """Tests for _build_content_parts_from_message function."""

    async def test_text_only_message(self, tmp_path: Path):
        """Should extract text content from message."""
        from copaw.app.channels.telegram.channel import (
            _build_content_parts_from_message,
        )

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_message.text = "Hello world"
        mock_message.caption = None
        mock_message.entities = []
        mock_message.caption_entities = None
        mock_message.photo = []
        mock_message.document = None
        mock_message.video = None
        mock_message.voice = None
        mock_message.audio = None
        mock_update.message = mock_message
        mock_update.edited_message = None

        mock_bot = MagicMock()
        mock_bot.username = "test_bot"
        mock_bot.id = "12345"

        (
            parts,
            has_command,
            is_mentioned,
        ) = await _build_content_parts_from_message(
            mock_update,
            bot=mock_bot,
            media_dir=tmp_path,
        )

        assert len(parts) == 1
        assert parts[0].type == ContentType.TEXT
        assert parts[0].text == "Hello world"
        assert has_command is False
        assert is_mentioned is False

    async def test_message_with_bot_command(self, tmp_path: Path):
        """Should detect bot command entities."""
        from copaw.app.channels.telegram.channel import (
            _build_content_parts_from_message,
        )

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_message.text = "/start"
        mock_message.caption = None

        mock_entity = MagicMock()
        mock_entity.type = "bot_command"
        mock_message.entities = [mock_entity]
        mock_message.caption_entities = None
        mock_message.photo = []
        mock_message.document = None
        mock_message.video = None
        mock_message.voice = None
        mock_message.audio = None

        mock_update.message = mock_message
        mock_update.edited_message = None

        mock_bot = MagicMock()
        mock_bot.username = "test_bot"
        mock_bot.id = "12345"

        (
            parts,
            has_command,
            _is_mentioned,
        ) = await _build_content_parts_from_message(
            mock_update,
            bot=mock_bot,
            media_dir=tmp_path,
        )

        assert has_command is True
        assert len(parts) == 1
        assert parts[0].text == "/start"

    async def test_message_with_mention(self, tmp_path: Path):
        """Should detect bot mention."""
        from copaw.app.channels.telegram.channel import (
            _build_content_parts_from_message,
        )

        mock_update = MagicMock()
        mock_message = MagicMock()
        mock_message.text = "@test_bot Hello"
        mock_message.caption = None

        mock_entity = MagicMock()
        mock_entity.type = "mention"
        mock_entity.offset = 0
        mock_entity.length = 9  # @test_bot
        mock_message.entities = [mock_entity]
        mock_message.caption_entities = None
        mock_message.photo = []
        mock_message.document = None
        mock_message.video = None
        mock_message.voice = None
        mock_message.audio = None

        mock_update.message = mock_message
        mock_update.edited_message = None

        mock_bot = MagicMock()
        mock_bot.username = "test_bot"
        mock_bot.id = "12345"

        (
            parts,
            _has_command,
            is_mentioned,
        ) = await _build_content_parts_from_message(
            mock_update,
            bot=mock_bot,
            media_dir=tmp_path,
        )

        assert is_mentioned is True
        # Mention should be removed from text
        assert "@test_bot" not in parts[0].text
        assert "Hello" in parts[0].text

    async def test_message_no_content(self, tmp_path: Path):
        """Should return empty list when no content."""
        from copaw.app.channels.telegram.channel import (
            _build_content_parts_from_message,
        )

        mock_update = MagicMock()
        mock_update.message = None
        mock_update.edited_message = None

        mock_bot = MagicMock()

        (
            parts,
            has_command,
            is_mentioned,
        ) = await _build_content_parts_from_message(
            mock_update,
            bot=mock_bot,
            media_dir=tmp_path,
        )

        assert parts == []
        assert has_command is False
        assert is_mentioned is False


# =============================================================================
# P2: Channel Lifecycle
# =============================================================================


@pytest.mark.asyncio
class TestTelegramLifecycle:
    """Tests for start/stop lifecycle."""

    async def test_start_disabled_channel(
        self,
        disabled_telegram_channel,
        caplog,
    ):
        """start should return early for disabled channel."""
        import logging

        with caplog.at_level(logging.DEBUG):
            await disabled_telegram_channel.start()

        # Should not create task
        assert disabled_telegram_channel._task is None

    async def test_start_no_token(self, telegram_channel, caplog):
        """start should return early when no token."""
        import logging

        telegram_channel._bot_token = ""

        with caplog.at_level(logging.DEBUG):
            await telegram_channel.start()

        assert telegram_channel._task is None

    async def test_stop_disabled_channel(self, disabled_telegram_channel):
        """stop should return early for disabled channel."""
        # Should not raise
        await disabled_telegram_channel.stop()

    async def test_stop_without_start(self, telegram_channel):
        """stop should succeed without prior start."""
        telegram_channel._task = None
        telegram_channel._application = None

        # Should not raise
        await telegram_channel.stop()


# =============================================================================
# P2: Exception Classes
# =============================================================================


class TestTelegramExceptions:
    """Tests for custom exception classes."""

    def test_file_too_large_error(self):
        """_FileTooLargeError should be catchable."""
        from copaw.app.channels.telegram.channel import _FileTooLargeError

        exc = _FileTooLargeError("File is too big")
        assert str(exc) == "File is too big"
        assert isinstance(exc, Exception)

    def test_media_file_unavailable_error(self):
        """_MediaFileUnavailableError should be catchable."""
        from copaw.app.channels.telegram.channel import (
            _MediaFileUnavailableError,
        )

        exc = _MediaFileUnavailableError("File not found")
        assert str(exc) == "File not found"
        assert isinstance(exc, Exception)


# =============================================================================
# P2: Constants
# =============================================================================


class TestTelegramConstants:
    """Tests for module constants."""

    def test_max_message_length(self):
        """TELEGRAM_MAX_MESSAGE_LENGTH should be 4096."""
        from copaw.app.channels.telegram.channel import (
            TELEGRAM_MAX_MESSAGE_LENGTH,
        )

        assert TELEGRAM_MAX_MESSAGE_LENGTH == 4096

    def test_send_chunk_size(self):
        """TELEGRAM_SEND_CHUNK_SIZE should be 4000."""
        from copaw.app.channels.telegram.channel import (
            TELEGRAM_SEND_CHUNK_SIZE,
        )

        assert TELEGRAM_SEND_CHUNK_SIZE == 4000

    def test_max_file_size(self):
        """TELEGRAM_MAX_FILE_SIZE_BYTES should be 50MB."""
        from copaw.app.channels.telegram.channel import (
            TELEGRAM_MAX_FILE_SIZE_BYTES,
        )

        assert TELEGRAM_MAX_FILE_SIZE_BYTES == 50 * 1024 * 1024


# =============================================================================
# P2: Proxy URL Building
# =============================================================================


class TestTelegramProxyUrl:
    """Tests for proxy URL construction."""

    def test_no_proxy_returns_none(self, telegram_channel):
        """_build_application should handle no proxy."""
        telegram_channel._http_proxy = ""
        telegram_channel._bot_token = "test_token"

        # Just test the _build_application method exists and can be called
        # without throwing during the proxy_url() function
        with patch("telegram.ext.Application.builder") as mock_builder_class:
            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder
            mock_builder.token.return_value = mock_builder
            mock_builder.get_updates_read_timeout.return_value = mock_builder
            mock_builder.get_updates_connect_timeout.return_value = (
                mock_builder
            )
            mock_builder.build.return_value = MagicMock()

            # Should complete without error
            telegram_channel._build_application()

            # No proxy methods should be called
            assert (
                not hasattr(mock_builder, "proxy")
                or not mock_builder.proxy.called
            )

    def test_proxy_without_auth(self, telegram_channel):
        """Should use proxy without auth when no auth provided."""
        telegram_channel._http_proxy = "http://proxy.example.com:8080"
        telegram_channel._http_proxy_auth = ""

        with patch("telegram.ext.Application.builder") as mock_builder_class:
            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder
            mock_builder.token.return_value = mock_builder
            mock_builder.get_updates_read_timeout.return_value = mock_builder
            mock_builder.get_updates_connect_timeout.return_value = (
                mock_builder
            )
            mock_builder.proxy.return_value = mock_builder
            mock_builder.get_updates_proxy.return_value = mock_builder
            mock_builder.build.return_value = MagicMock()

            telegram_channel._build_application()

            mock_builder.proxy.assert_called_once_with(
                "http://proxy.example.com:8080",
            )

    def test_proxy_with_auth(self, telegram_channel):
        """Should include auth in proxy URL when provided."""
        telegram_channel._http_proxy = "http://proxy.example.com:8080"
        telegram_channel._http_proxy_auth = "user:pass"

        with patch("telegram.ext.Application.builder") as mock_builder_class:
            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder
            mock_builder.token.return_value = mock_builder
            mock_builder.get_updates_read_timeout.return_value = mock_builder
            mock_builder.get_updates_connect_timeout.return_value = (
                mock_builder
            )
            mock_builder.proxy.return_value = mock_builder
            mock_builder.get_updates_proxy.return_value = mock_builder
            mock_builder.build.return_value = MagicMock()

            telegram_channel._build_application()

            expected_proxy = "http://user:pass@proxy.example.com:8080"
            mock_builder.proxy.assert_called_once_with(expected_proxy)
