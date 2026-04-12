# -*- coding: utf-8 -*-
"""
WeCom (Enterprise WeChat) Channel Unit Tests

Comprehensive unit tests for WecomChannel covering:
- Initialization and configuration
- Factory methods (from_env, from_config)
- Session ID resolution and routing
- Message deduplication (thread safety)
- Message handling (text, image, voice, file, video, mixed)
- Media upload and download
- Send methods
- Lifecycle (start/stop)

Test Patterns:
- Async tests with @pytest.mark.asyncio on async methods only
- No global pytestmark
- Uses tmp_path for temporary files
- Thread safety tests for deduplication

Run:
    pytest tests/unit/channels/test_wecom.py -v
    pytest tests/unit/channels/test_wecom.py::TestWecomChannelInit -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=broad-exception-raised
from __future__ import annotations

import threading
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from copaw.exceptions import ChannelError


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
def wecom_channel(
    mock_process_handler,
    tmp_path: Path,
) -> Generator:
    """Create a WecomChannel instance for testing."""
    from copaw.app.channels.wecom.channel import WecomChannel

    channel = WecomChannel(
        process=mock_process_handler,
        enabled=True,
        bot_id="test_bot_id_123",
        secret="test_secret_456",
        bot_prefix="[WeComBot] ",
        media_dir=str(tmp_path / "media"),
        welcome_text="Welcome to WeCom Bot!",
        show_tool_details=False,
        filter_tool_messages=True,
        dm_policy="open",
        group_policy="open",
    )
    yield channel


@pytest.fixture
def mock_ws_client() -> MagicMock:
    """Create mock WebSocket client."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = Mock()
    client.reply = AsyncMock()
    client.reply_stream = AsyncMock()
    client.reply_welcome = AsyncMock()
    client.send_message = AsyncMock()
    client.download_file = AsyncMock(
        return_value=(b"mock_file_data", "test.jpg"),
    )

    # Mock ws_manager
    client._ws_manager = MagicMock()
    client._ws_manager.send = AsyncMock()
    client._ws_manager.on_message = Mock()

    return client


@pytest.fixture
def sample_text_frame() -> dict:
    """Create a sample text message frame."""
    return {
        "body": {
            "msgid": "msg_123",
            "msgtype": "text",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
            "send_time": "1234567890",
            "text": {"content": "Hello, bot!"},
        },
    }


@pytest.fixture
def sample_image_frame() -> dict:
    """Create a sample image message frame."""
    return {
        "body": {
            "msgid": "msg_456",
            "msgtype": "image",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
            "send_time": "1234567890",
            "image": {
                "url": "https://example.com/image.jpg",
                "aeskey": "test_aes_key",
            },
        },
    }


@pytest.fixture
def sample_voice_frame() -> dict:
    """Create a sample voice message frame."""
    return {
        "body": {
            "msgid": "msg_789",
            "msgtype": "voice",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
            "send_time": "1234567890",
            "voice": {
                "content": "Voice message text",
            },
        },
    }


@pytest.fixture
def sample_file_frame() -> dict:
    """Create a sample file message frame."""
    return {
        "body": {
            "msgid": "msg_file",
            "msgtype": "file",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
            "send_time": "1234567890",
            "file": {
                "url": "https://example.com/file.pdf",
                "aeskey": "test_aes_key",
                "filename": "document.pdf",
            },
        },
    }


@pytest.fixture
def sample_video_frame() -> dict:
    """Create a sample video message frame."""
    return {
        "body": {
            "msgid": "msg_video",
            "msgtype": "video",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
            "send_time": "1234567890",
            "video": {
                "url": "https://example.com/video.mp4",
                "aeskey": "test_aes_key",
            },
        },
    }


@pytest.fixture
def sample_mixed_frame() -> dict:
    """Create a sample mixed message frame."""
    return {
        "body": {
            "msgid": "msg_mixed",
            "msgtype": "mixed",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
            "send_time": "1234567890",
            "mixed": {
                "msg_item": [
                    {"msgtype": "text", "text": {"content": "First text"}},
                    {
                        "msgtype": "image",
                        "image": {
                            "url": "https://example.com/img.jpg",
                            "aeskey": "aes_key",
                        },
                    },
                    {"msgtype": "text", "text": {"content": "Second text"}},
                ],
            },
        },
    }


@pytest.fixture
def sample_group_frame() -> dict:
    """Create a sample group chat message frame."""
    return {
        "body": {
            "msgid": "msg_group",
            "msgtype": "text",
            "from": {"userid": "user_123"},
            "chatid": "group_456",
            "chattype": "group",
            "send_time": "1234567890",
            "text": {"content": "Hello group!"},
        },
    }


@pytest.fixture
def sample_enter_chat_frame() -> dict:
    """Create a sample enter_chat event frame."""
    return {
        "body": {
            "event": "enter_chat",
            "from": {"userid": "user_123"},
            "chatid": "chat_456",
            "chattype": "single",
        },
    }


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestWecomChannelInit:
    """
    P0: WecomChannel initialization tests.
    """

    def test_init_stores_basic_config(
        self,
        mock_process_handler,
        tmp_path: Path,
    ):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.wecom.channel import WecomChannel

        channel = WecomChannel(
            process=mock_process_handler,
            enabled=True,
            bot_id="bot_123",
            secret="secret_456",
            bot_prefix="[Bot] ",
            media_dir=str(tmp_path / "media"),
            welcome_text="Welcome!",
            dm_policy="open",
            group_policy="allowlist",
        )

        assert channel.enabled is True
        assert channel.bot_id == "bot_123"
        assert channel.secret == "secret_456"
        assert channel.bot_prefix == "[Bot] "
        assert channel.welcome_text == "Welcome!"
        assert channel.channel == "wecom"
        assert channel.dm_policy == "open"
        assert channel.group_policy == "allowlist"

    def test_init_stores_advanced_config(
        self,
        mock_process_handler,
        tmp_path: Path,
    ):
        """Constructor should store advanced configuration parameters."""
        from copaw.app.channels.wecom.channel import WecomChannel

        channel = WecomChannel(
            process=mock_process_handler,
            enabled=False,
            bot_id="",
            secret="",
            bot_prefix="",
            media_dir=str(tmp_path / "media"),
            show_tool_details=True,
            filter_tool_messages=True,
            filter_thinking=True,
            allow_from=["user1", "user2"],
            deny_message="Access denied",
            max_reconnect_attempts=5,
        )

        assert channel.enabled is False
        assert channel._show_tool_details is True
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True
        assert channel.allow_from == {"user1", "user2"}
        assert channel.deny_message == "Access denied"
        assert channel._max_reconnect_attempts == 5

    def test_init_creates_required_data_structures(self, mock_process_handler):
        """Constructor should initialize required internal data structures."""
        from copaw.app.channels.wecom.channel import WecomChannel

        channel = WecomChannel(
            process=mock_process_handler,
            enabled=True,
            bot_id="bot123",
            secret="secret",
        )

        assert hasattr(channel, "_processed_message_ids")
        assert isinstance(channel._processed_message_ids, dict)
        assert hasattr(channel, "_processed_ids_lock")
        assert isinstance(channel._processed_ids_lock, type(threading.Lock()))
        assert channel._client is None
        assert channel._ws_thread is None

    def test_channel_type_is_wecom(self, wecom_channel):
        """Channel type must be 'wecom'."""
        assert wecom_channel.channel == "wecom"

    def test_uses_manager_queue_is_true(self, wecom_channel):
        """WeCom channel uses manager queue."""
        assert wecom_channel.uses_manager_queue is True


# =============================================================================
# P0: Factory Method Tests
# =============================================================================


class TestWecomChannelFromEnv:
    """
    P0: Tests for from_env factory method.
    """

    def test_from_env_reads_basic_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read basic environment variables."""
        from copaw.app.channels.wecom.channel import WecomChannel

        monkeypatch.setenv("WECOM_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("WECOM_BOT_ID", "env_bot_id")
        monkeypatch.setenv("WECOM_SECRET", "env_secret")
        monkeypatch.setenv("WECOM_BOT_PREFIX", "[EnvBot] ")
        monkeypatch.setenv("WECOM_MEDIA_DIR", "/env/media")
        # Note: welcome_text is not read from env in from_env, defaults to empty

        channel = WecomChannel.from_env(mock_process_handler)

        assert channel.enabled is True
        assert channel.bot_id == "env_bot_id"
        assert channel.secret == "env_secret"
        assert channel.bot_prefix == "[EnvBot] "
        # welcome_text defaults to empty string in from_env
        assert channel.welcome_text == ""

    def test_from_env_reads_policy_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read policy environment variables."""
        from copaw.app.channels.wecom.channel import WecomChannel

        monkeypatch.setenv("WECOM_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("WECOM_BOT_ID", "bot_id")
        monkeypatch.setenv("WECOM_SECRET", "secret")
        monkeypatch.setenv("WECOM_DM_POLICY", "allowlist")
        monkeypatch.setenv("WECOM_GROUP_POLICY", "deny")
        monkeypatch.setenv("WECOM_ALLOW_FROM", "user1,user2,user3")
        monkeypatch.setenv("WECOM_DENY_MESSAGE", "Custom deny message")
        monkeypatch.setenv("WECOM_MAX_RECONNECT_ATTEMPTS", "10")

        channel = WecomChannel.from_env(mock_process_handler)

        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "deny"
        assert channel.allow_from == {"user1", "user2", "user3"}
        assert channel.deny_message == "Custom deny message"
        assert channel._max_reconnect_attempts == 10

    def test_from_env_disabled_by_default(self, mock_process_handler):
        """from_env should create disabled channel by default."""
        from copaw.app.channels.wecom.channel import WecomChannel

        channel = WecomChannel.from_env(mock_process_handler)

        assert channel.enabled is False
        assert channel.bot_id == ""
        assert channel.secret == ""

    def test_from_env_empty_allow_from(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should handle empty allow_from."""
        from copaw.app.channels.wecom.channel import WecomChannel

        monkeypatch.setenv("WECOM_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("WECOM_BOT_ID", "bot_id")
        monkeypatch.setenv("WECOM_SECRET", "secret")
        monkeypatch.setenv("WECOM_ALLOW_FROM", "")

        channel = WecomChannel.from_env(mock_process_handler)

        assert channel.allow_from == set()


class TestWecomChannelFromConfig:
    """
    P0: Tests for from_config factory method.
    """

    def test_from_config_reads_basic_config(self, mock_process_handler):
        """from_config should read basic configuration."""
        from copaw.app.channels.wecom.channel import WecomChannel

        config = MagicMock()
        config.enabled = True
        config.bot_id = "config_bot_id"
        config.secret = "config_secret"
        config.bot_prefix = "[Config] "
        config.media_dir = "/config/media"
        config.welcome_text = "Config welcome"
        config.dm_policy = "allowlist"
        config.group_policy = "deny"
        config.allow_from = ["user1"]
        config.deny_message = "Go away"
        config.max_reconnect_attempts = 3

        channel = WecomChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is True
        assert channel.bot_id == "config_bot_id"
        assert channel.secret == "config_secret"
        assert channel.bot_prefix == "[Config] "
        assert channel.welcome_text == "Config welcome"
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "deny"
        assert channel.allow_from == {"user1"}
        assert channel.deny_message == "Go away"
        assert channel._max_reconnect_attempts == 3

    def test_from_config_handles_none_values(self, mock_process_handler):
        """from_config should handle None values gracefully."""
        from copaw.app.channels.wecom.channel import WecomChannel

        config = MagicMock()
        config.enabled = False  # Use False instead of None
        config.bot_id = None
        config.secret = None
        config.bot_prefix = None
        config.media_dir = None
        config.welcome_text = None
        config.dm_policy = None
        config.group_policy = None
        config.allow_from = None
        config.deny_message = None
        config.max_reconnect_attempts = None

        channel = WecomChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is False
        assert channel.bot_id == ""
        assert channel.secret == ""
        assert channel.bot_prefix == ""
        assert channel.welcome_text == ""
        assert channel.dm_policy == "open"
        assert channel.group_policy == "open"
        assert channel.allow_from == set()
        assert channel.deny_message == ""
        assert channel._max_reconnect_attempts == -1


# =============================================================================
# P0: Session ID Resolution Tests
# =============================================================================


class TestWecomChannelSessionResolution:
    """
    P0: Tests for session ID resolution and routing.
    """

    def test_resolve_session_id_single_chat(self, wecom_channel):
        """resolve_session_id should return wecom:user for single chat."""
        session_id = wecom_channel.resolve_session_id(
            sender_id="user_123",
            channel_meta={"wecom_chat_type": "single"},
        )
        assert session_id == "wecom:user_123"

    def test_resolve_session_id_group_chat(self, wecom_channel):
        """resolve_session_id returns wecom:group:chatid for group chat."""
        session_id = wecom_channel.resolve_session_id(
            sender_id="user_123",
            channel_meta={
                "wecom_chat_type": "group",
                "wecom_chatid": "group_456",
            },
        )
        assert session_id == "wecom:group:group_456"

    def test_resolve_session_id_fallback_to_chatid(self, wecom_channel):
        """resolve_session_id falls back to chatid if no sender_id."""
        session_id = wecom_channel.resolve_session_id(
            sender_id="",
            channel_meta={"wecom_chatid": "chat_789"},
        )
        assert session_id == "wecom:chat_789"

    def test_resolve_session_id_unknown(self, wecom_channel):
        """resolve_session_id returns wecom:unknown for empty identifiers."""
        session_id = wecom_channel.resolve_session_id(
            sender_id="",
            channel_meta={},
        )
        assert session_id == "wecom:unknown"

    def test_parse_chatid_from_handle_single(self, wecom_channel):
        """_parse_chatid_from_handle extracts userid from single chat."""
        chatid = wecom_channel._parse_chatid_from_handle("wecom:user_123")
        assert chatid == "user_123"

    def test_parse_chatid_from_handle_group(self, wecom_channel):
        """_parse_chatid_from_handle extracts chatid from group."""
        chatid = wecom_channel._parse_chatid_from_handle(
            "wecom:group:group_123",
        )
        assert chatid == "group_123"

    def test_parse_chatid_from_handle_plain(self, wecom_channel):
        """_parse_chatid_from_handle returns plain string as-is."""
        chatid = wecom_channel._parse_chatid_from_handle("plain_id")
        assert chatid == "plain_id"

    def test_to_handle_from_target_with_session(self, wecom_channel):
        """to_handle_from_target should use session_id when provided."""
        handle = wecom_channel.to_handle_from_target(
            user_id="user_123",
            session_id="wecom:session_456",
        )
        assert handle == "wecom:session_456"

    def test_to_handle_from_target_without_session(self, wecom_channel):
        """to_handle_from_target should fallback to user_id when no session."""
        handle = wecom_channel.to_handle_from_target(
            user_id="user_123",
            session_id="",
        )
        assert handle == "wecom:user_123"

    def test_get_to_handle_from_request_with_session(self, wecom_channel):
        """get_to_handle_from_request should use session_id when available."""
        request = MagicMock()
        request.session_id = "wecom:user_123"
        request.user_id = "user_456"

        handle = wecom_channel.get_to_handle_from_request(request)
        assert handle == "wecom:user_123"

    def test_get_to_handle_from_request_without_session(self, wecom_channel):
        """get_to_handle_from_request should fallback to user_id."""
        request = MagicMock()
        request.session_id = ""
        request.user_id = "user_456"

        handle = wecom_channel.get_to_handle_from_request(request)
        assert handle == "wecom:user_456"

    def test_get_on_reply_sent_args(self, wecom_channel):
        """get_on_reply_sent_args should return (user_id, session_id)."""
        request = MagicMock()
        request.user_id = "user_123"
        request.session_id = "wecom:session_456"

        args = wecom_channel.get_on_reply_sent_args(
            request,
            "wecom:session_456",
        )
        assert args == ("user_123", "wecom:session_456")


# =============================================================================
# P0: Message Deduplication Tests
# =============================================================================


class TestWecomChannelDeduplication:
    """
    P0: Tests for message deduplication.
    """

    def test_is_duplicate_new_message(self, wecom_channel):
        """_is_duplicate should return False for new message."""
        result = wecom_channel._is_duplicate("msg123")
        assert result is False

    def test_is_duplicate_existing_message(self, wecom_channel):
        """_is_duplicate should return True for duplicate message."""
        wecom_channel._is_duplicate("msg123")
        result = wecom_channel._is_duplicate("msg123")
        assert result is True

    def test_is_duplicate_thread_safety(self, wecom_channel):
        """_is_duplicate should be thread-safe."""
        results = []

        def check_duplicate(msg_id):
            results.append(wecom_channel._is_duplicate(msg_id))

        threads = [
            threading.Thread(target=check_duplicate, args=(f"msg_{i}",))
            for i in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All first occurrences should be False
        assert all(r is False for r in results)

    def test_processed_ids_limit(self, wecom_channel):
        """_is_duplicate should limit stored message IDs."""
        from copaw.app.channels.wecom.channel import _WECOM_PROCESSED_IDS_MAX

        # Add many message IDs
        for i in range(_WECOM_PROCESSED_IDS_MAX + 100):
            wecom_channel._is_duplicate(f"msg_{i}")

        # Check that limit is respected
        assert (
            len(wecom_channel._processed_message_ids)
            <= _WECOM_PROCESSED_IDS_MAX
        )


# =============================================================================
# P0: Build Agent Request Tests
# =============================================================================


class TestWecomChannelBuildAgentRequest:
    """
    P0: Tests for building AgentRequest from native payload.
    """

    def test_build_agent_request_from_native_basic(self, wecom_channel):
        """build_agent_request_from_native creates proper AgentRequest."""
        from agentscope_runtime.engine.schemas.agent_schemas import TextContent

        payload = {
            "channel_id": "wecom",
            "sender_id": "user_123",
            "content_parts": [TextContent(type="text", text="Hello")],
            "meta": {"wecom_chatid": "chat_456", "wecom_chat_type": "single"},
        }

        request = wecom_channel.build_agent_request_from_native(payload)

        assert request.channel == "wecom"
        assert request.user_id == "user_123"
        assert hasattr(request, "channel_meta")
        assert request.channel_meta["wecom_chatid"] == "chat_456"

    def test_build_agent_request_from_native_defaults(self, wecom_channel):
        """build_agent_request_from_native uses defaults for missing fields."""
        request = wecom_channel.build_agent_request_from_native({})

        assert request.channel == "wecom"
        assert hasattr(request, "session_id")

    def test_build_agent_request_from_native_non_dict(self, wecom_channel):
        """build_agent_request_from_native should handle non-dict input."""
        request = wecom_channel.build_agent_request_from_native("invalid")

        assert request.channel == "wecom"


# =============================================================================
# P0: Merge Native Items Tests
# =============================================================================


class TestWecomChannelMergeNativeItems:
    """
    P0: Tests for merging native items.
    """

    def test_merge_native_items_empty_list(self, wecom_channel):
        """merge_native_items should return None for empty list."""
        result = wecom_channel.merge_native_items([])
        assert result is None

    def test_merge_native_items_single_item(self, wecom_channel):
        """merge_native_items should handle single item."""
        items = [{"content_parts": [{"type": "text", "text": "Hello"}]}]

        result = wecom_channel.merge_native_items(items)

        assert result["content_parts"] == [{"type": "text", "text": "Hello"}]

    def test_merge_native_items_multiple_items(self, wecom_channel):
        """merge_native_items should concatenate content_parts."""
        items = [
            {"content_parts": [{"type": "text", "text": "Hello"}]},
            {"content_parts": [{"type": "text", "text": "World"}]},
            {"content_parts": [{"type": "image", "url": "img.jpg"}]},
        ]

        result = wecom_channel.merge_native_items(items)

        assert len(result["content_parts"]) == 3
        assert result["content_parts"][0]["text"] == "Hello"
        assert result["content_parts"][1]["text"] == "World"


# =============================================================================
# P1: Async Handler Tests
# =============================================================================


class TestWecomChannelMessageHandlers:
    """
    P1: Tests for message handling (async methods).
    """

    @pytest.mark.asyncio
    async def test_on_message_text(
        self,
        wecom_channel,
        sample_text_frame,
        mock_ws_client,
    ):
        """_on_message should handle text messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        # Mock _enqueue to capture the native payload
        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        await wecom_channel._on_message(sample_text_frame)

        assert len(enqueued_items) == 1
        assert enqueued_items[0]["channel_id"] == "wecom"
        assert enqueued_items[0]["sender_id"] == "user_123"

    @pytest.mark.asyncio
    async def test_on_message_duplicate_dropped(
        self,
        wecom_channel,
        sample_text_frame,
        mock_ws_client,
    ):
        """_on_message should drop duplicate messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        # First message
        await wecom_channel._on_message(sample_text_frame)
        assert len(enqueued_items) == 1

        # Duplicate message - should be dropped
        await wecom_channel._on_message(sample_text_frame)
        assert len(enqueued_items) == 1

    @pytest.mark.asyncio
    async def test_on_message_image(
        self,
        wecom_channel,
        sample_image_frame,
        mock_ws_client,
        tmp_path,
    ):
        """_on_message should handle image messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        await wecom_channel._on_message(sample_image_frame)

        assert len(enqueued_items) == 1
        mock_ws_client.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_message_voice(
        self,
        wecom_channel,
        sample_voice_frame,
        mock_ws_client,
    ):
        """_on_message should handle voice messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        await wecom_channel._on_message(sample_voice_frame)

        assert len(enqueued_items) == 1
        assert len(enqueued_items[0]["content_parts"]) > 0

    @pytest.mark.asyncio
    async def test_on_message_file(
        self,
        wecom_channel,
        sample_file_frame,
        mock_ws_client,
        tmp_path,
    ):
        """_on_message should handle file messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        await wecom_channel._on_message(sample_file_frame)

        assert len(enqueued_items) == 1
        mock_ws_client.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_message_video(
        self,
        wecom_channel,
        sample_video_frame,
        mock_ws_client,
        tmp_path,
    ):
        """_on_message should handle video messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        await wecom_channel._on_message(sample_video_frame)

        assert len(enqueued_items) == 1
        mock_ws_client.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_message_mixed(
        self,
        wecom_channel,
        sample_mixed_frame,
        mock_ws_client,
        tmp_path,
    ):
        """_on_message should handle mixed messages."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        await wecom_channel._on_message(sample_mixed_frame)

        assert len(enqueued_items) == 1
        # Should have text and image parts
        assert len(enqueued_items[0]["content_parts"]) >= 2

    @pytest.mark.asyncio
    async def test_on_message_allowlist_blocked(
        self,
        wecom_channel,
        sample_text_frame,
        mock_ws_client,
    ):
        """_on_message should block non-allowlisted users."""
        wecom_channel.dm_policy = "allowlist"
        wecom_channel.allow_from = {"other_user"}
        wecom_channel.deny_message = "You are not allowed"

        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        await wecom_channel._on_message(sample_text_frame)

        # Should send denial message
        mock_ws_client.reply_stream.assert_called()

    @pytest.mark.asyncio
    async def test_on_enter_chat(
        self,
        wecom_channel,
        sample_enter_chat_frame,
        mock_ws_client,
    ):
        """_on_enter_chat should send welcome message."""
        wecom_channel._client = mock_ws_client
        wecom_channel.welcome_text = "Welcome!"

        await wecom_channel._on_enter_chat(sample_enter_chat_frame)

        mock_ws_client.reply_welcome.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_enter_chat_no_welcome(
        self,
        wecom_channel,
        sample_enter_chat_frame,
        mock_ws_client,
    ):
        """_on_enter_chat should do nothing if no welcome_text."""
        wecom_channel._client = mock_ws_client
        wecom_channel.welcome_text = ""

        await wecom_channel._on_enter_chat(sample_enter_chat_frame)

        mock_ws_client.reply_welcome.assert_not_called()


# =============================================================================
# P1: Download Media Tests
# =============================================================================


class TestWecomChannelDownloadMedia:
    """
    P1: Tests for media download functionality.
    """

    @pytest.mark.asyncio
    async def test_download_media_success(
        self,
        wecom_channel,
        mock_ws_client,
        tmp_path,
    ):
        """_download_media should download and save file."""
        wecom_channel._client = mock_ws_client
        wecom_channel._media_dir = tmp_path

        path = await wecom_channel._download_media(
            "https://example.com/file.jpg",
            aes_key="test_key",
            filename_hint="image.jpg",
        )

        assert path is not None
        assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_download_media_no_client(self, wecom_channel):
        """_download_media should return None if no client."""
        path = await wecom_channel._download_media(
            "https://example.com/file.jpg",
        )

        assert path is None

    @pytest.mark.asyncio
    async def test_download_media_failure(self, wecom_channel, mock_ws_client):
        """_download_media should handle download failure gracefully."""
        mock_ws_client.download_file.side_effect = Exception("Download failed")
        wecom_channel._client = mock_ws_client

        path = await wecom_channel._download_media(
            "https://example.com/file.jpg",
        )

        assert path is None


# =============================================================================
# P1: Send Content Tests
# =============================================================================


class TestWecomChannelSendMethods:
    """
    P1: Tests for send methods.
    """

    @pytest.mark.asyncio
    async def test_send_content_parts_disabled(self, wecom_channel):
        """send_content_parts should do nothing if disabled."""
        wecom_channel.enabled = False

        await wecom_channel.send_content_parts(
            "wecom:user_123",
            [],
            {},
        )

        # Should not raise or do anything

    @pytest.mark.asyncio
    async def test_send_content_parts_text_only(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """send_content_parts should send text content."""
        wecom_channel._client = mock_ws_client
        from agentscope_runtime.engine.schemas.agent_schemas import TextContent

        parts = [TextContent(type="text", text="Hello World")]
        meta = {"wecom_frame": {"test": "frame"}}

        await wecom_channel.send_content_parts(
            "wecom:user_123",
            parts,
            meta,
        )

        mock_ws_client.reply_stream.assert_called()

    @pytest.mark.asyncio
    async def test_send_content_parts_with_prefix(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """send_content_parts should apply bot prefix."""
        wecom_channel._client = mock_ws_client
        wecom_channel.bot_prefix = "[Bot]"
        from agentscope_runtime.engine.schemas.agent_schemas import TextContent

        parts = [TextContent(type="text", text="Hello")]

        await wecom_channel.send_content_parts(
            "wecom:user_123",
            parts,
            {"wecom_frame": {"test": "frame"}},
        )

        mock_ws_client.reply_stream.assert_called()
        call_args = mock_ws_client.reply_stream.call_args
        assert "[Bot]" in call_args.kwargs.get("content", "")

    @pytest.mark.asyncio
    async def test_send_content_parts_proactive(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """send_content_parts should use send_message when no frame."""
        wecom_channel._client = mock_ws_client
        from agentscope_runtime.engine.schemas.agent_schemas import TextContent

        parts = [TextContent(type="text", text="Hello")]

        await wecom_channel.send_content_parts(
            "wecom:user_123",
            parts,
            {"wecom_chatid": "chat_456"},  # No frame, proactive send
        )

        mock_ws_client.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_send_disabled(self, wecom_channel, mock_ws_client):
        """send should do nothing if disabled."""
        wecom_channel.enabled = False
        wecom_channel._client = mock_ws_client

        await wecom_channel.send("wecom:user_123", "Hello")

        mock_ws_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_proactive(self, wecom_channel, mock_ws_client):
        """send should work in proactive mode."""
        wecom_channel._client = mock_ws_client

        await wecom_channel.send(
            "wecom:user_123",
            "Hello World",
            {"wecom_chatid": "chat_456"},
        )

        mock_ws_client.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_send_text_via_frame(self, wecom_channel, mock_ws_client):
        """_send_text_via_frame should send via reply_stream."""
        wecom_channel._client = mock_ws_client

        await wecom_channel._send_text_via_frame(
            {"test": "frame"},
            "Hello",
        )

        mock_ws_client.reply_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_text_via_frame_no_text(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """_send_text_via_frame should do nothing with empty text."""
        wecom_channel._client = mock_ws_client

        await wecom_channel._send_text_via_frame(
            {"test": "frame"},
            "",
        )

        mock_ws_client.reply_stream.assert_not_called()


# =============================================================================
# P1: Media Upload Tests
# =============================================================================


class TestWecomChannelMediaUpload:
    """
    P1: Tests for media upload functionality.
    """

    @pytest.mark.asyncio
    async def test_upload_media_success(
        self,
        wecom_channel,
        mock_ws_client,
        tmp_path,
    ):
        """_upload_media should upload file and return media_id."""
        wecom_channel._client = mock_ws_client
        wecom_channel._upload_lock = MagicMock()

        # Mock _send_ws_cmd to simulate upload flow
        wecom_channel._send_ws_cmd = AsyncMock(
            side_effect=[
                {"upload_id": "upload_123"},  # init
                {},  # chunk
                {"media_id": "media_456"},  # finish
            ],
        )

        # Create test file
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"test image data")

        media_id = await wecom_channel._upload_media(
            str(test_file),
            "image",
        )

        assert media_id == "media_456"

    @pytest.mark.asyncio
    async def test_upload_media_no_client(self, wecom_channel, tmp_path):
        """_upload_media should return None if no client."""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"test data")

        media_id = await wecom_channel._upload_media(str(test_file), "image")

        assert media_id is None

    @pytest.mark.asyncio
    async def test_upload_media_file_not_found(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """_upload_media should return None if file not found."""
        wecom_channel._client = mock_ws_client
        wecom_channel._upload_lock = MagicMock()

        media_id = await wecom_channel._upload_media(
            "/nonexistent/file.jpg",
            "image",
        )

        assert media_id is None

    @pytest.mark.asyncio
    async def test_upload_media_empty_upload_id(
        self,
        wecom_channel,
        mock_ws_client,
        tmp_path,
    ):
        """_upload_media should handle empty upload_id."""
        wecom_channel._client = mock_ws_client
        wecom_channel._upload_lock = MagicMock()

        # Return empty upload_id - implementation catches RuntimeError internally
        wecom_channel._send_ws_cmd = AsyncMock(return_value={"upload_id": ""})

        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"test data")

        # The implementation catches the RuntimeError and returns None
        result = await wecom_channel._upload_media(str(test_file), "image")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_ws_cmd_success(self, wecom_channel, mock_ws_client):
        """_send_ws_cmd should send command and await ack."""
        wecom_channel._client = mock_ws_client

        # Create future and set result
        loop = MagicMock()
        loop.create_future = MagicMock()
        mock_fut = MagicMock()
        mock_fut.done.return_value = False
        mock_fut.result = {"body": {"status": "ok"}, "errcode": 0}
        loop.create_future.return_value = mock_fut

        with patch("asyncio.get_event_loop", return_value=loop):
            # Need to actually create a proper future
            import asyncio

            real_fut = asyncio.Future()
            real_fut.set_result(
                {
                    "body": {"result": "success"},
                    "errcode": 0,
                },
            )
            loop.create_future.return_value = real_fut

            result = await wecom_channel._send_ws_cmd(
                "test_cmd",
                {"key": "value"},
            )

        assert result == {"result": "success"}


# =============================================================================
# P1: Lifecycle Tests
# =============================================================================


class TestWecomChannelLifecycle:
    """
    P1: Tests for channel lifecycle (start/stop).
    """

    @pytest.mark.asyncio
    async def test_start_disabled(self, wecom_channel):
        """start should do nothing if disabled."""
        wecom_channel.enabled = False

        await wecom_channel.start()

        assert wecom_channel._client is None

    @pytest.mark.asyncio
    async def test_start_missing_credentials(self, wecom_channel):
        """start should raise error if credentials missing."""
        wecom_channel.bot_id = ""
        wecom_channel.secret = ""

        with pytest.raises(
            ChannelError,
            match="WECOM_BOT_ID and WECOM_SECRET",
        ):
            await wecom_channel.start()

    @pytest.mark.asyncio
    async def test_stop_disabled(self, wecom_channel):
        """stop should do nothing if disabled."""
        wecom_channel.enabled = False

        await wecom_channel.stop()

        # Should not raise

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, wecom_channel, mock_ws_client):
        """stop should clean up resources."""
        wecom_channel._client = mock_ws_client
        wecom_channel._ws_thread = MagicMock()

        await wecom_channel.stop()

        mock_ws_client.disconnect.assert_called_once()
        assert wecom_channel._client is None


# =============================================================================
# P2: Edge Case Tests
# =============================================================================


class TestWecomChannelEdgeCases:
    """
    P2: Edge case tests.
    """

    def test_on_message_sync_no_loop(self, wecom_channel, sample_text_frame):
        """_on_message_sync should log warning if no loop."""
        wecom_channel._loop = None

        # Should not raise, just log warning
        wecom_channel._on_message_sync(sample_text_frame)

    @pytest.mark.asyncio
    async def test_on_message_unknown_type(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """_on_message should handle unknown message types."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        frame = {
            "body": {
                "msgid": "msg_unknown",
                "msgtype": "unknown_type",
                "from": {"userid": "user_123"},
                "chattype": "single",
                "text": {"content": ""},
            },
        }

        await wecom_channel._on_message(frame)

        # Should still process with placeholder text
        assert len(enqueued_items) == 1
        # Check content_parts contains the unknown type marker
        assert any(
            "unknown_type" in str(part)
            for part in enqueued_items[0]["content_parts"]
        )

    @pytest.mark.asyncio
    async def test_on_message_image_no_url(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """_on_message should handle image without URL."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        frame = {
            "body": {
                "msgid": "msg_img",
                "msgtype": "image",
                "from": {"userid": "user_123"},
                "chattype": "single",
                "image": {},  # No URL
            },
        }

        await wecom_channel._on_message(frame)

        assert len(enqueued_items) == 1
        # Should have placeholder text
        assert any(
            "no url" in str(part).lower()
            for part in enqueued_items[0]["content_parts"]
        )

    @pytest.mark.asyncio
    async def test_on_message_voice_no_text(
        self,
        wecom_channel,
        mock_ws_client,
    ):
        """_on_message should handle voice without ASR text."""
        wecom_channel._client = mock_ws_client
        wecom_channel._loop = MagicMock()
        wecom_channel._loop.is_running.return_value = True

        enqueued_items = []
        wecom_channel._enqueue = enqueued_items.append

        frame = {
            "body": {
                "msgid": "msg_voice",
                "msgtype": "voice",
                "from": {"userid": "user_123"},
                "chattype": "single",
                "voice": {},  # No content
            },
        }

        await wecom_channel._on_message(frame)

        assert len(enqueued_items) == 1
        # Should have placeholder text
        assert any(
            "no text" in str(part).lower()
            for part in enqueued_items[0]["content_parts"]
        )

    @pytest.mark.asyncio
    async def test_send_media_part_image(
        self,
        wecom_channel,
        mock_ws_client,
        tmp_path,
    ):
        """_send_media_part should handle image parts."""
        wecom_channel._client = mock_ws_client
        wecom_channel._upload_media = AsyncMock(return_value="media_123")

        from agentscope_runtime.engine.schemas.agent_schemas import (
            ImageContent,
        )

        part = ImageContent(type="image", image_url=str(tmp_path / "test.jpg"))

        await wecom_channel._send_media_part(
            "chat_123",
            part,
            {"test": "frame"},
        )

        wecom_channel._upload_media.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_media_part_audio(
        self,
        wecom_channel,
        mock_ws_client,
        tmp_path,
    ):
        """_send_media_part should handle audio parts."""
        wecom_channel._client = mock_ws_client
        wecom_channel._upload_media = AsyncMock(return_value="media_123")

        # Create AMR file
        amr_file = tmp_path / "test.amr"
        amr_file.write_bytes(b"amr data")

        from agentscope_runtime.engine.schemas.agent_schemas import (
            AudioContent,
        )

        part = AudioContent(type="audio", data=str(amr_file))

        await wecom_channel._send_media_part(
            "chat_123",
            part,
            {"test": "frame"},
        )

        wecom_channel._upload_media.assert_called_once()
        # Should detect as voice (AMR format)
        call_args = wecom_channel._upload_media.call_args
        assert call_args[0][1] in ["voice", "file"]
