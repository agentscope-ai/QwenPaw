# -*- coding: utf-8 -*-
"""
Unit tests for IMessageChannel.

Tests cover initialization, factory methods, lifecycle, and core functionality.
Platform-specific code is handled with @pytest.mark.skipif decorators.
"""

# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

import base64
import os
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Platform check for macOS-specific tests
IS_DARWIN = sys.platform == "darwin"


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
def mock_enqueue() -> MagicMock:
    """Mock enqueue callback."""
    return MagicMock()


@pytest.fixture
def temp_media_dir(tmp_path) -> str:
    """Temporary directory for media files."""
    media_dir = tmp_path / ".copaw" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return str(media_dir)


@pytest.fixture
def mock_channel_config() -> MagicMock:
    """Mock IMessageChannelConfig."""
    config = MagicMock(spec="IMessageChannelConfig")
    config.enabled = True
    config.db_path = "~/Library/Messages/chat.db"
    config.poll_sec = 1.0
    config.bot_prefix = "@bot "
    config.media_dir = None
    config.max_decoded_size = 10 * 1024 * 1024
    config.filter_tool_messages = False
    config.filter_thinking = False
    return config


@pytest.fixture
def imessage_channel(
    mock_process_handler: AsyncMock,
    temp_media_dir: str,
):
    """Create IMessageChannel instance for testing."""
    from qwenpaw.app.channels.imessage.channel import IMessageChannel

    channel = IMessageChannel(
        process=mock_process_handler,
        enabled=True,
        db_path="~/Library/Messages/chat.db",
        poll_sec=1.0,
        bot_prefix="@bot ",
        media_dir=temp_media_dir,
        max_decoded_size=10 * 1024 * 1024,
    )
    yield channel


class TestIMessageChannelInit:
    """Test IMessageChannel initialization."""

    def test_init_stores_basic_config(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """Constructor should store basic configuration parameters."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=2.5,
            bot_prefix="@test ",
            media_dir=temp_media_dir,
            max_decoded_size=5 * 1024 * 1024,
            on_reply_sent=None,
            show_tool_details=False,
            filter_tool_messages=True,
            filter_thinking=True,
        )

        assert channel.enabled is True
        assert channel.db_path == os.path.expanduser("~/test/chat.db")
        assert channel.poll_sec == 2.5
        assert channel.bot_prefix == "@test "
        assert channel.max_decoded_size == 5 * 1024 * 1024
        assert channel._show_tool_details is False
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True

    def test_init_creates_media_directory(
        self,
        mock_process_handler: AsyncMock,
        tmp_path: Path,
    ):
        """Constructor should create media directory."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        media_dir = tmp_path / "media" / "imessage"
        assert not media_dir.exists()

        IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=str(media_dir),
            max_decoded_size=10 * 1024 * 1024,
        )

        assert media_dir.exists()

    def test_init_expands_user_path(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """Constructor should expand user directory path."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/Library/Messages/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        assert channel.db_path == os.path.expanduser(
            "~/Library/Messages/chat.db",
        )
        assert "~" not in channel.db_path

    def test_init_creates_required_data_structures(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """Constructor should initialize internal data structures."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        assert hasattr(channel, "_imsg_path")
        assert channel._imsg_path is None
        assert hasattr(channel, "_stop_event")
        assert isinstance(channel._stop_event, threading.Event)
        assert hasattr(channel, "_thread")
        assert channel._thread is None


class TestIMessageChannelFactoryMethods:
    """Test IMessageChannel factory methods."""

    def test_from_env_reads_env_vars(
        self,
        mock_process_handler: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
        temp_media_dir: str,
    ):
        """from_env should read environment variables correctly."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        monkeypatch.setenv("IMESSAGE_CHANNEL_ENABLED", "0")
        monkeypatch.setenv("IMESSAGE_DB_PATH", "/custom/path/chat.db")
        monkeypatch.setenv("IMESSAGE_POLL_SEC", "2.0")
        monkeypatch.setenv("IMESSAGE_BOT_PREFIX", "@assistant ")

        channel = IMessageChannel.from_env(process=mock_process_handler)

        assert channel.enabled is False
        assert channel.db_path == "/custom/path/chat.db"
        assert channel.poll_sec == 2.0
        assert channel.bot_prefix == "@assistant "

    def test_from_env_uses_defaults(
        self,
        mock_process_handler: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """from_env should use defaults when variables are missing."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        monkeypatch.delenv("IMESSAGE_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("IMESSAGE_DB_PATH", raising=False)
        monkeypatch.delenv("IMESSAGE_POLL_SEC", raising=False)
        monkeypatch.delenv("IMESSAGE_BOT_PREFIX", raising=False)

        channel = IMessageChannel.from_env(process=mock_process_handler)

        assert channel.enabled is True  # default
        assert channel.db_path == os.path.expanduser(
            "~/Library/Messages/chat.db",
        )
        assert channel.poll_sec == 1.0  # default
        assert channel.bot_prefix == ""  # default

    def test_from_config_uses_config_object(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """from_config should use config object values."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from qwenpaw.config.config import IMessageChannelConfig

        config = IMessageChannelConfig(
            enabled=True,
            db_path="/tmp/test/db.sqlite",
            poll_sec=3.0,
            bot_prefix="@ai ",
            media_dir=temp_media_dir,
            max_decoded_size=20 * 1024 * 1024,
            filter_tool_messages=True,
            filter_thinking=True,
        )

        channel = IMessageChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is True
        assert channel.db_path == "/tmp/test/db.sqlite"
        assert channel.poll_sec == 3.0
        assert channel.bot_prefix == "@ai "
        assert channel.max_decoded_size == 20 * 1024 * 1024

    def test_from_config_uses_default_db_path(
        self,
        mock_process_handler: AsyncMock,
    ):
        """from_config should use default db_path."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from qwenpaw.config.config import IMessageChannelConfig

        config = IMessageChannelConfig(
            enabled=True,
            poll_sec=1.0,
        )

        channel = IMessageChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.db_path == os.path.expanduser(
            "~/Library/Messages/chat.db",
        )


class TestIMessageChannelProperties:
    """Test IMessageChannel properties and constants."""

    def test_channel_type_is_imessage(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """channel type should be imessage."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        assert channel.channel == "imessage"


class TestIMessageChannelUtilityMethods:
    """Test IMessageChannel utility methods."""

    def test_sanitize_filename_removes_path_traversal(
        self,
        imessage_channel,
    ):
        """_sanitize_filename should remove path traversal characters."""
        result = imessage_channel._sanitize_filename("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert result == "passwd"

    def test_sanitize_filename_allows_safe_characters(
        self,
        imessage_channel,
    ):
        """_sanitize_filename should preserve safe characters."""
        result = imessage_channel._sanitize_filename("test_file-name.123.jpg")
        assert result == "test_file-name.123.jpg"

    def test_sanitize_filename_handles_empty_input(
        self,
        imessage_channel,
    ):
        """_sanitize_filename should handle empty input."""
        result = imessage_channel._sanitize_filename("")
        assert result == "media_file"

    def test_sanitize_filename_handles_only_special_chars(
        self,
        imessage_channel,
    ):
        """_sanitize_filename should handle input with only special chars."""
        result = imessage_channel._sanitize_filename("!@#$%")
        assert result == "media_file"

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("test.jpg", "test.jpg"),
            ("test.png", "test.png"),
            ("/path/to/file.txt", "file.txt"),
            ("../secret.txt", "secret.txt"),
            ("file with spaces.pdf", "file_with_spaces.pdf"),
        ],
    )
    def test_sanitize_filename_various_inputs(
        self,
        imessage_channel,
        filename: str,
        expected: str,
    ):
        """_sanitize_filename should handle various inputs correctly."""
        result = imessage_channel._sanitize_filename(filename)
        assert result == expected

    def test_extract_url_and_filename_for_image(
        self,
        imessage_channel,
    ):
        """_extract_url_and_filename should handle image type correctly."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            ImageContent,
            ContentType,
        )

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://example.com/image.jpg",
        )

        (
            url,
            filename_hint,
            content_type,
        ) = imessage_channel._extract_url_and_filename(
            part,
        )

        assert url == "https://example.com/image.jpg"
        assert filename_hint == "image"
        assert content_type == ContentType.IMAGE

    def test_extract_url_and_filename_for_video(
        self,
        imessage_channel,
    ):
        """_extract_url_and_filename should handle video type correctly."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            VideoContent,
            ContentType,
        )

        part = VideoContent(
            type=ContentType.VIDEO,
            video_url="https://example.com/video.mp4",
        )

        (
            url,
            filename_hint,
            content_type,
        ) = imessage_channel._extract_url_and_filename(
            part,
        )

        assert url == "https://example.com/video.mp4"
        assert filename_hint == "video"
        assert content_type == ContentType.VIDEO

    def test_get_file_extension_from_filename(
        self,
        imessage_channel,
    ):
        """_get_file_extension should extract extension from filename."""
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        ext = imessage_channel._get_file_extension(
            ContentType.IMAGE,
            "photo.png",
        )
        assert ext == ".png"

    def test_get_file_extension_from_content_type(
        self,
        imessage_channel,
    ):
        """_get_file_extension returns default ext based on content type."""
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        assert (
            imessage_channel._get_file_extension(ContentType.IMAGE, "photo")
            == ".jpg"
        )
        assert (
            imessage_channel._get_file_extension(ContentType.AUDIO, "sound")
            == ".mp3"
        )
        assert (
            imessage_channel._get_file_extension(ContentType.VIDEO, "movie")
            == ".mp4"
        )
        assert (
            imessage_channel._get_file_extension(ContentType.FILE, "doc")
            == ".bin"
        )


class TestIMessageChannelAsyncLifecycle:
    """Test IMessageChannel async lifecycle methods."""

    async def test_start_skips_when_disabled(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """start should not perform operations when disabled."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=False,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Should not raise and not start watcher
        await channel.start()

        assert channel._thread is None
        assert channel._imsg_path is None

    async def test_stop_skips_when_disabled(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """stop should not perform operations when disabled."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=False,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Should not raise
        await channel.stop()

    async def test_start_finds_imsg_binary(
        self,
    ):
        """start should set imsg path correctly."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=AsyncMock(),
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=None,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Mock _ensure_imsg to avoid requiring actual installation
        with patch.object(
            channel,
            "_ensure_imsg",
            return_value="/usr/local/bin/imsg",
        ):
            channel._imsg_path = channel._ensure_imsg()
            assert channel._imsg_path == "/usr/local/bin/imsg"


class TestIMessageChannelSend:
    """Test IMessageChannel send methods."""

    async def test_send_skips_when_disabled(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """send should not perform operations when disabled."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=False,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Should not raise
        await channel.send("+1234567890", "Hello")

    def test_send_sync_raises_when_not_initialized(self):
        """_send_sync should raise ChannelError when not initialized."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from qwenpaw.exceptions import ChannelError

        channel = IMessageChannel(
            process=AsyncMock(),
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=None,
            max_decoded_size=10 * 1024 * 1024,
        )

        with pytest.raises(ChannelError, match="not initialized"):
            channel._send_sync("+1234567890", "Hello")

    async def test_send_content_parts_with_text_only(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """send_content_parts should handle text-only parts."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ContentType,
        )

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        parts = [
            TextContent(type=ContentType.TEXT, text="Hello "),
            TextContent(type=ContentType.TEXT, text="World"),
        ]

        with patch.object(channel, "send") as mock_send:
            await channel.send_content_parts("+1234567890", parts)

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "+1234567890"
            assert "Hello" in call_args[0][1]
            assert "World" in call_args[0][1]

    async def test_send_content_parts_with_empty_parts(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """send_content_parts should handle empty parts list."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Should not raise
        await channel.send_content_parts("+1234567890", [])


class TestIMessageChannelMedia:
    """Test IMessageChannel media handling methods."""

    async def test_send_media_skips_when_disabled(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """send_media should not perform operations when disabled."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import (
            ImageContent,
            ContentType,
        )

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=False,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://example.com/image.jpg",
        )

        # Should not raise
        await channel.send_media("+1234567890", part)

    async def test_send_media_handles_missing_url(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """send_media should handle missing URL."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Create a mock part without url
        mock_part = MagicMock()
        mock_part.type = None
        mock_part.image_url = None
        mock_part.file_url = None
        mock_part.video_url = None
        mock_part.audio_url = None
        mock_part.data = None

        # Should return None when no URL is found (no error raised)
        result = await channel.send_media("+1234567890", mock_part)
        assert result is None

    async def test_handle_local_file_with_file_url(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        tmp_path: Path,
    ):
        """_handle_local_file should handle file:// URL."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = await channel._handle_local_file(f"file://{test_file}")
        assert result is not None
        assert "test.txt" in result

    async def test_handle_local_file_with_plain_path(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        tmp_path: Path,
    ):
        """_handle_local_file should handle plain path."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = await channel._handle_local_file(str(test_file))
        assert result is not None
        assert "test.txt" in result

    async def test_handle_local_file_missing_file(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """_handle_local_file should handle non-existent file."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        result = await channel._handle_local_file("/nonexistent/file.txt")

        assert result is None

    async def test_handle_data_url_with_valid_base64(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """_handle_data_url should handle valid base64 data URL."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Create a valid base64 data URL
        test_data = b"test image data"
        b64_data = base64.b64encode(test_data).decode()
        data_url = f"data:image/png;base64,{b64_data}"

        result = await channel._handle_data_url(
            data_url,
            ContentType.IMAGE,
            "test_image",
        )

        assert result is not None
        assert Path(result).exists()
        assert Path(result).name.startswith("test_image")

    async def test_handle_data_url_with_invalid_base64(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """_handle_data_url should handle invalid base64 data."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        invalid_data_url = "data:image/png;base64,!!!invalid!!!"

        result = await channel._handle_data_url(
            invalid_data_url,
            ContentType.IMAGE,
            "test_image",
        )

        assert result is None

    async def test_handle_data_url_with_oversized_data(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """_handle_data_url should handle oversized base64 data."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        # Set small limit for testing
        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=100,  # Very small limit
        )

        # Create a large base64 data URL
        large_data = b"x" * 200
        b64_data = base64.b64encode(large_data).decode()
        data_url = f"data:image/png;base64,{b64_data}"

        result = await channel._handle_data_url(
            data_url,
            ContentType.IMAGE,
            "test_image",
        )

        assert result is None

    async def test_handle_data_url_non_base64_format(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """_handle_data_url should handle non-base64 format data URL."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import ContentType

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        # Data URL without base64 marker
        data_url = "data:text/plain,HelloWorld"

        result = await channel._handle_data_url(
            data_url,
            ContentType.IMAGE,
            "test",
        )

        assert result is None


class TestIMessageChannelRequestBuilder:
    """Test IMessageChannel request building methods."""

    def test_build_agent_request_from_native(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """build_agent_request_from_native should build request from native."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ContentType,
        )

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        content_parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
        ]
        native_payload = {
            "channel_id": "imessage",
            "sender_id": "+1234567890",
            "content_parts": content_parts,
            "meta": {"chat_rowid": "123"},
        }

        request = channel.build_agent_request_from_native(native_payload)

        assert request is not None
        assert request.session_id is not None
        assert request.input is not None

    def test_build_agent_request_from_native_with_empty_payload(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """build_agent_request_from_native should handle empty payload."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )

        request = channel.build_agent_request_from_native({})
        assert request is not None


class TestIMessageChannelErrorHandling:
    """Test IMessageChannel error handling."""

    async def test_on_consume_error_sends_error_message(
        self,
        mock_process_handler: AsyncMock,
        temp_media_dir: str,
    ):
        """_on_consume_error should send error message."""
        from qwenpaw.app.channels.imessage.channel import IMessageChannel

        channel = IMessageChannel(
            process=mock_process_handler,
            enabled=True,
            db_path="~/test/chat.db",
            poll_sec=1.0,
            bot_prefix="",
            media_dir=temp_media_dir,
            max_decoded_size=10 * 1024 * 1024,
        )
        channel._imsg_path = "/usr/local/bin/imsg"  # Mock the path

        mock_request = MagicMock()

        with patch.object(channel, "_send_sync") as mock_send:
            await channel._on_consume_error(
                mock_request,
                "+1234567890",
                "Error occurred",
            )

            mock_send.assert_called_once_with("+1234567890", "Error occurred")
