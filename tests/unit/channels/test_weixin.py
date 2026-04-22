# -*- coding: utf-8 -*-
"""
WeChat (Weixin) Channel Unit Tests

Comprehensive unit tests for WeixinChannel covering:
- Initialization and configuration
- Factory methods (from_env, from_config)
- Session ID resolution and routing
- Token persistence (save/load)
- Message deduplication (thread safety)
- HTTP API interactions (mocked)
- Send methods
- Media download
- Lifecycle (start/stop)

Test Patterns:
- Uses MockAiohttpSession for HTTP request mocking
- Async tests with pytest.mark.asyncio
- Thread safety tests for deduplication

Run:
    pytest tests/unit/channels/test_weixin.py -v
    pytest tests/unit/channels/test_weixin.py::TestWeixinChannelInit -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=broad-exception-raised,using-constant-test
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures.channels.mock_http import MockAiohttpSession


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
def temp_media_dir(tmp_path) -> Path:
    """Temporary directory for media files."""
    media_dir = tmp_path / ".copaw" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


@pytest.fixture
def temp_token_dir(tmp_path) -> Path:
    """Temporary directory for token files."""
    token_dir = tmp_path / ".copaw"
    token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir


@pytest.fixture
def weixin_channel(
    mock_process_handler,
    temp_media_dir,
) -> Generator:
    """Create a WeixinChannel instance for testing."""
    from qwenpaw.app.channels.weixin.channel import WeixinChannel

    channel = WeixinChannel(
        process=mock_process_handler,
        enabled=True,
        bot_token="test_token_123",
        bot_prefix="[TestBot] ",
        media_dir=str(temp_media_dir),
        show_tool_details=False,
        filter_tool_messages=True,
        dm_policy="open",
        group_policy="open",
    )
    yield channel


@pytest.fixture
def mock_http_session() -> MockAiohttpSession:
    """Create a mock aiohttp session."""
    return MockAiohttpSession()


@pytest.fixture
def mock_ilink_client() -> MagicMock:
    """Create a mock ILinkClient."""
    client = MagicMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.get_bot_qrcode = AsyncMock(
        return_value={
            "qrcode": "qr_code_string",
            "qrcode_img_content": "base64_encoded_image",
            "url": "https://example.com/qr",
        },
    )
    client.wait_for_login = AsyncMock(
        return_value=("new_token_123", "https://api.weixin.com"),
    )
    client.send_text = AsyncMock(return_value={"ret": 0})
    client.getupdates = AsyncMock(
        return_value={
            "ret": 0,
            "get_updates_buf": "cursor_123",
            "msgs": [],
        },
    )
    client.download_media = AsyncMock(return_value=b"mock_media_data")
    client.bot_token = "test_token"
    client.base_url = "https://ilinkai.weixin.qq.com"
    return client


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestWeixinChannelInit:
    """
    Tests for WeixinChannel initialization and factory methods.
    Verifies correct storage of configuration parameters.
    """

    def test_init_stores_basic_config(
        self,
        mock_process_handler,
        temp_media_dir,
    ):
        """Constructor should store all basic configuration parameters."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token="my_token_123",
            bot_prefix="[Bot] ",
            media_dir=str(temp_media_dir),
            dm_policy="open",
            group_policy="allowlist",
        )

        assert channel.enabled is True
        assert channel.bot_token == "my_token_123"
        assert channel.bot_prefix == "[Bot] "
        assert channel.channel == "wechat"
        assert channel.dm_policy == "open"
        assert channel.group_policy == "allowlist"

    def test_init_stores_advanced_config(
        self,
        mock_process_handler,
        temp_media_dir,
    ):
        """Constructor should store advanced configuration parameters."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=False,
            bot_token="",
            bot_token_file="/custom/path/token.txt",
            base_url="https://custom.api.com",
            bot_prefix="",
            media_dir=str(temp_media_dir),
            show_tool_details=True,
            filter_tool_messages=True,
            filter_thinking=True,
            allow_from=["user1", "user2"],
            deny_message="Access denied",
        )

        assert channel.enabled is False
        assert channel._base_url == "https://custom.api.com"
        assert channel._show_tool_details is True
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True
        assert channel.allow_from == {"user1", "user2"}
        assert channel.deny_message == "Access denied"

    def test_init_creates_required_data_structures(self, mock_process_handler):
        """Constructor should initialize required internal data structures."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
        )

        # Message dedup store
        assert hasattr(channel, "_processed_ids")
        assert isinstance(channel._processed_ids, dict)

        # User context tokens cache
        assert hasattr(channel, "_user_context_tokens")
        assert isinstance(channel._user_context_tokens, dict)

        # Cursor for long-polling
        assert hasattr(channel, "_cursor")
        assert channel._cursor == ""

    def test_init_creates_locks(self, mock_process_handler):
        """Constructor should create required locks for thread safety."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
        )

        # Deduplication lock
        assert hasattr(channel, "_processed_ids_lock")
        lock_type = type(channel._processed_ids_lock).__name__
        assert "lock" in lock_type.lower()

    def test_channel_type_is_wechat(self, weixin_channel):
        """Channel type must be 'wechat'."""
        assert weixin_channel.channel == "wechat"


class TestWeixinChannelFromEnv:
    """Tests for from_env factory method."""

    def test_from_env_reads_basic_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read basic environment variables."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        monkeypatch.setenv("WEIXIN_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("WEIXIN_BOT_TOKEN", "env_token_123")
        monkeypatch.setenv("WEIXIN_BOT_PREFIX", "[EnvBot] ")
        monkeypatch.setenv("WEIXIN_BASE_URL", "https://env.api.com")

        channel = WeixinChannel.from_env(mock_process_handler)

        assert channel.enabled is True
        assert channel.bot_token == "env_token_123"
        assert channel.bot_prefix == "[EnvBot] "
        assert channel._base_url == "https://env.api.com"

    def test_from_env_reads_advanced_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read advanced environment variables."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        monkeypatch.setenv("WEIXIN_BOT_TOKEN_FILE", "/env/token/file.txt")
        monkeypatch.setenv("WEIXIN_MEDIA_DIR", "/env/media")
        monkeypatch.setenv("WEIXIN_DM_POLICY", "allowlist")
        monkeypatch.setenv("WEIXIN_GROUP_POLICY", "allowlist")
        monkeypatch.setenv("WEIXIN_DENY_MESSAGE", "Env access denied")

        channel = WeixinChannel.from_env(mock_process_handler)

        assert (
            channel._bot_token_file == Path("/env/token/file.txt").expanduser()
        )
        assert channel._media_dir == Path("/env/media").expanduser()
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"
        assert channel.deny_message == "Env access denied"

    def test_from_env_allow_from_parsing(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should parse WEIXIN_ALLOW_FROM correctly."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        monkeypatch.setenv("WEIXIN_ALLOW_FROM", "user1,user2,user3")

        channel = WeixinChannel.from_env(mock_process_handler)

        assert "user1" in channel.allow_from
        assert "user2" in channel.allow_from
        assert "user3" in channel.allow_from

    def test_from_env_allow_from_empty(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should handle empty WEIXIN_ALLOW_FROM."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        monkeypatch.setenv("WEIXIN_ALLOW_FROM", "")

        channel = WeixinChannel.from_env(mock_process_handler)

        assert channel.allow_from == set()

    def test_from_env_defaults(self, mock_process_handler, monkeypatch):
        """from_env should use sensible defaults."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        monkeypatch.delenv("WEIXIN_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("WEIXIN_BOT_PREFIX", raising=False)
        monkeypatch.delenv("WEIXIN_DM_POLICY", raising=False)
        monkeypatch.delenv("WEIXIN_GROUP_POLICY", raising=False)

        channel = WeixinChannel.from_env(mock_process_handler)

        assert channel.enabled is False  # Default disabled
        assert channel.bot_prefix == ""  # Default empty
        assert channel.dm_policy == "open"  # Default open
        assert channel.group_policy == "open"  # Default open


class TestWeixinChannelFromConfig:
    """Tests for from_config factory method."""

    def test_from_config_uses_config_values(self, mock_process_handler):
        """from_config should use values from config object."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        class MockConfig:
            enabled = True
            bot_token = "config_token_123"
            bot_token_file = "/config/token.txt"
            base_url = "https://config.api.com"
            bot_prefix = "[ConfigBot] "
            media_dir = "/config/media"
            dm_policy = "allowlist"
            group_policy = "allowlist"
            allow_from = ["user1", "user2"]
            deny_message = "Config denied"

        config = MockConfig()
        channel = WeixinChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is True
        assert channel.bot_token == "config_token_123"
        assert channel.bot_prefix == "[ConfigBot] "
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"

    def test_from_config_handles_none_values(self, mock_process_handler):
        """from_config should handle None values gracefully."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        class MockConfig:
            enabled = False  # Use False instead of None
            bot_token = None
            bot_prefix = None
            dm_policy = None
            group_policy = None

        config = MockConfig()
        channel = WeixinChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is False
        assert channel.bot_token == ""
        assert channel.bot_prefix == ""
        assert channel.dm_policy == "open"
        assert channel.group_policy == "open"


# =============================================================================
# P1: Session ID Resolution and Routing
# =============================================================================


class TestWeixinResolveSession:
    """Tests for session resolution and routing helpers."""

    def test_resolve_session_id_private_chat(self, weixin_channel):
        """resolve_session_id should format private chat session ID."""
        result = weixin_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={},
        )

        assert result == "weixin:user123"

    def test_resolve_session_id_group_chat(self, weixin_channel):
        """resolve_session_id should format group chat session ID."""
        result = weixin_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={"weixin_group_id": "group456"},
        )

        assert result == "weixin:group:group456"

    def test_resolve_session_id_unknown(self, weixin_channel):
        """resolve_session_id should handle unknown sender."""
        result = weixin_channel.resolve_session_id(
            sender_id="",
            channel_meta={},
        )

        assert result == "weixin:unknown"

    def test_parse_user_id_from_handle_private(self, weixin_channel):
        """_parse_user_id_from_handle extracts user ID from private handle."""
        result = weixin_channel._parse_user_id_from_handle("weixin:user123")

        assert result == "user123"

    def test_parse_user_id_from_handle_group(self, weixin_channel):
        """_parse_user_id_from_handle extracts group ID from group handle."""
        result = weixin_channel._parse_user_id_from_handle(
            "weixin:group:group456",
        )

        assert result == "group456"

    def test_parse_user_id_from_handle_plain(self, weixin_channel):
        """_parse_user_id_from_handle should return plain ID."""
        result = weixin_channel._parse_user_id_from_handle("plain_user_id")

        assert result == "plain_user_id"

    def test_to_handle_from_target_with_session(self, weixin_channel):
        """to_handle_from_target should prefer session_id."""
        result = weixin_channel.to_handle_from_target(
            user_id="user123",
            session_id="weixin:session_abc",
        )

        assert result == "weixin:session_abc"

    def test_to_handle_from_target_fallback_to_user(self, weixin_channel):
        """to_handle_from_target should fallback to user_id when no session."""
        result = weixin_channel.to_handle_from_target(
            user_id="user123",
            session_id="",
        )

        assert result == "weixin:user123"

    def test_get_to_handle_from_request(self, weixin_channel):
        """get_to_handle_from_request should extract handle from request."""
        mock_request = MagicMock()
        mock_request.session_id = "weixin:session_abc"
        mock_request.user_id = "user123"

        result = weixin_channel.get_to_handle_from_request(mock_request)

        assert result == "weixin:session_abc"

    def test_get_on_reply_sent_args(self, weixin_channel):
        """get_on_reply_sent_args should return correct tuple."""
        mock_request = MagicMock()
        mock_request.user_id = "user123"
        mock_request.session_id = "weixin:session_abc"

        result = weixin_channel.get_on_reply_sent_args(
            mock_request,
            "weixin:session_abc",
        )

        assert result == ("user123", "weixin:session_abc")


# =============================================================================
# P1: Token Persistence
# =============================================================================


class TestWeixinTokenPersistence:
    """Tests for bot_token persistence to/from file."""

    def test_load_token_from_file_success(
        self,
        mock_process_handler,
        temp_token_dir,
    ):
        """Should load token from file when available."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        token_file = temp_token_dir / "weixin_bot_token"
        token_file.write_text("persisted_token_123", encoding="utf-8")

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token_file=str(token_file),
        )

        result = channel._load_token_from_file()

        assert result == "persisted_token_123"

    def test_load_token_from_file_not_exists(
        self,
        mock_process_handler,
        temp_token_dir,
    ):
        """Should return empty string when file doesn't exist."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token_file=str(temp_token_dir / "nonexistent"),
        )

        result = channel._load_token_from_file()

        assert result == ""

    def test_save_token_to_file_creates_file(
        self,
        mock_process_handler,
        temp_token_dir,
    ):
        """Should create token file with correct content."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        token_file = temp_token_dir / "weixin_bot_token"
        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token_file=str(token_file),
        )

        channel._save_token_to_file("new_token_456")

        assert token_file.exists()
        assert token_file.read_text(encoding="utf-8") == "new_token_456"

    def test_save_token_creates_parent_dirs(
        self,
        mock_process_handler,
        tmp_path,
    ):
        """Should create parent directories if needed."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        deep_path = tmp_path / "deep" / "nested" / "dir" / "token"
        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token_file=str(deep_path),
        )

        channel._save_token_to_file("token_123")

        assert deep_path.exists()

    def test_load_context_tokens_from_file(
        self,
        mock_process_handler,
        temp_token_dir,
    ):
        """Should load context tokens from file."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        context_file = temp_token_dir / "weixin_context_tokens.json"
        data = {"user1": "token1", "user2": "token2"}
        context_file.write_text(json.dumps(data), encoding="utf-8")

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token_file=str(temp_token_dir / "weixin_bot_token"),
        )
        channel._load_context_tokens()

        assert channel._user_context_tokens == {
            "user1": "token1",
            "user2": "token2",
        }

    def test_save_context_tokens_to_file(
        self,
        mock_process_handler,
        temp_token_dir,
    ):
        """Should save context tokens to file."""
        from qwenpaw.app.channels.weixin.channel import WeixinChannel

        channel = WeixinChannel(
            process=mock_process_handler,
            enabled=True,
            bot_token_file=str(temp_token_dir / "weixin_bot_token"),
        )
        channel._user_context_tokens = {"user1": "token1", "user2": "token2"}

        channel._save_context_tokens()

        context_file = temp_token_dir / "weixin_context_tokens.json"
        assert context_file.exists()
        data = json.loads(context_file.read_text(encoding="utf-8"))
        assert data == {"user1": "token1", "user2": "token2"}


# =============================================================================
# P1: Message Deduplication (Thread Safety)
# =============================================================================


class TestWeixinMessageDedup:
    """Tests for message deduplication mechanism."""

    def test_is_duplicate_new_message(self, weixin_channel):
        """Should return False for new message ID."""
        result = weixin_channel._is_duplicate("msg_unique_123")

        assert result is False
        assert "msg_unique_123" in weixin_channel._processed_ids

    def test_is_duplicate_duplicate_message(self, weixin_channel):
        """Should return True for duplicate message ID."""
        # First call
        weixin_channel._is_duplicate("msg_dup_123")

        # Second call (duplicate)
        result = weixin_channel._is_duplicate("msg_dup_123")

        assert result is True

    def test_is_duplicate_is_thread_safe(self, weixin_channel):
        """Deduplication should be thread-safe."""
        accepted_count = [0]
        rejected_count = [0]

        def try_accept():
            for i in range(100):
                msg_id = f"batch_msg_{i % 10}"  # 10 unique IDs, 10 times each
                if weixin_channel._is_duplicate(msg_id):
                    rejected_count[0] += 1
                else:
                    accepted_count[0] += 1

        threads = [threading.Thread(target=try_accept) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 10 accepted (one for each unique ID)
        assert accepted_count[0] == 10
        # Rest should be rejected
        assert rejected_count[0] == 490

    def test_is_duplicate_max_size_limit(self, weixin_channel):
        """Should limit processed_ids size."""
        # Add more than max IDs
        max_size = 2000  # _WEIXIN_PROCESSED_IDS_MAX

        for i in range(max_size + 100):
            weixin_channel._is_duplicate(f"msg_{i}")

        assert len(weixin_channel._processed_ids) <= max_size


# =============================================================================
# P1: Build Agent Request
# =============================================================================


class TestWeixinBuildAgentRequest:
    """Tests for build_agent_request_from_native method."""

    def test_build_agent_request_from_native(self, weixin_channel):
        """Should create AgentRequest from native payload."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        payload = {
            "channel_id": "wechat",
            "sender_id": "user123",
            "user_id": "user123",
            "session_id": "weixin:session_abc",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {"weixin_group_id": "group123"},
        }

        request = weixin_channel.build_agent_request_from_native(payload)

        assert request.user_id == "user123"
        assert request.channel == "wechat"
        assert request.session_id == "weixin:session_abc"
        assert hasattr(request, "channel_meta")
        assert request.channel_meta.get("weixin_group_id") == "group123"

    def test_build_agent_request_auto_session(self, weixin_channel):
        """Should auto-generate session_id when not provided."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        payload = {
            "channel_id": "wechat",
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {},
        }

        request = weixin_channel.build_agent_request_from_native(payload)

        assert request.session_id == "weixin:user123"

    def test_merge_native_items(self, weixin_channel):
        """Should merge multiple native payloads."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        items = [
            {
                "channel_id": "wechat",
                "sender_id": "user1",
                "content_parts": [
                    TextContent(type=ContentType.TEXT, text="Part1"),
                ],
                "meta": {"key1": "value1"},
            },
            {
                "content_parts": [
                    TextContent(type=ContentType.TEXT, text="Part2"),
                ],
                "meta": {"key2": "value2"},
            },
        ]

        result = weixin_channel.merge_native_items(items)

        assert result["channel_id"] == "wechat"
        assert result["sender_id"] == "user1"
        assert len(result["content_parts"]) == 2
        assert result["meta"].get("key2") == "value2"

    def test_merge_native_items_empty(self, weixin_channel):
        """Should return None for empty list."""
        result = weixin_channel.merge_native_items([])

        assert result is None


# =============================================================================
# P1: HTTP API Interactions (Mock Tests)
# =============================================================================


@pytest.mark.asyncio
class TestWeixinSendMethods:
    """Tests for send methods using HTTP mocking."""

    async def test_send_text_direct_success(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Successfully send text message."""
        weixin_channel._client = mock_ilink_client

        await weixin_channel._send_text_direct(
            to_user_id="user123",
            text="Hello World",
            context_token="token_abc",
            client=mock_ilink_client,
        )

        mock_ilink_client.send_text.assert_called_once_with(
            "user123",
            "Hello World",
            "token_abc",
        )

    async def test_send_text_direct_no_client(self, weixin_channel):
        """Should return early when no client available."""
        weixin_channel._client = None

        # Should not raise
        result = await weixin_channel._send_text_direct(
            to_user_id="user123",
            text="Hello",
            context_token="token_abc",
        )

        assert result is None

    async def test_send_text_direct_no_user_id(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should return early when no user_id."""
        weixin_channel._client = mock_ilink_client

        await weixin_channel._send_text_direct(
            to_user_id="",
            text="Hello",
            context_token="token_abc",
        )

        mock_ilink_client.send_text.assert_not_called()

    async def test_send_text_direct_empty_response_is_success(
        self,
        weixin_channel,
        mock_ilink_client,
        caplog,
    ):
        """iLinkAI's sendmessage returns an empty dict on success. The
        previous implementation defaulted missing ``ret`` to 1 and treated
        every successful call as ``rejected``, which masked working sends
        behind a stream of WARNING logs. Must not warn; must log ok."""
        mock_ilink_client.send_text = AsyncMock(return_value={})
        weixin_channel._client = mock_ilink_client

        with caplog.at_level("INFO"):
            await weixin_channel._send_text_direct(
                to_user_id="user123",
                text="Hello",
                context_token="token_abc",
                client=mock_ilink_client,
            )

        assert any(
            "send_text ok" in r.message and r.levelname == "INFO"
            for r in caplog.records
        )
        assert not any("rejected" in r.message for r in caplog.records)

    async def test_send_text_direct_nonzero_ret_is_rejected(
        self,
        weixin_channel,
        mock_ilink_client,
        caplog,
    ):
        """A server-surfaced non-zero ``ret`` must log WARNING and abort
        (no ``ok`` log)."""
        mock_ilink_client.send_text = AsyncMock(return_value={"ret": 1})
        weixin_channel._client = mock_ilink_client

        with caplog.at_level("INFO"):
            await weixin_channel._send_text_direct(
                to_user_id="user123",
                text="Hello",
                context_token="token_abc",
                client=mock_ilink_client,
            )

        assert any(
            "send_text rejected" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        )
        assert not any("send_text ok" in r.message for r in caplog.records)

    async def test_send_text_direct_nonzero_errcode_is_rejected(
        self,
        weixin_channel,
        mock_ilink_client,
        caplog,
    ):
        """A non-zero ``errcode`` (even with ``ret`` absent or zero) must
        also be treated as rejection, not success."""
        mock_ilink_client.send_text = AsyncMock(
            return_value={"errcode": 123, "errmsg": "limit exceeded"},
        )
        weixin_channel._client = mock_ilink_client

        with caplog.at_level("INFO"):
            await weixin_channel._send_text_direct(
                to_user_id="user123",
                text="Hello",
                context_token="token_abc",
                client=mock_ilink_client,
            )

        assert any(
            "send_text rejected" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        )
        assert not any("send_text ok" in r.message for r in caplog.records)

    async def test_send_text_direct_non_dict_response_is_unexpected(
        self,
        weixin_channel,
        mock_ilink_client,
        caplog,
    ):
        """If the upstream contract drifts (e.g. returns ``None``, a list,
        or a string), we must surface that explicitly rather than silently
        claiming success. Otherwise a future protocol change would look
        like 'everything works' while messages vanish again."""
        mock_ilink_client.send_text = AsyncMock(return_value=None)
        weixin_channel._client = mock_ilink_client

        with caplog.at_level("INFO"):
            await weixin_channel._send_text_direct(
                to_user_id="user123",
                text="Hello",
                context_token="token_abc",
                client=mock_ilink_client,
            )

        assert any(
            "unexpected response shape" in r.message
            and r.levelname == "WARNING"
            for r in caplog.records
        )
        assert not any("send_text ok" in r.message for r in caplog.records)
        assert not any("send_text rejected" in r.message for r in caplog.records)

    async def test_send_content_parts_success(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Successfully send content parts."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        weixin_channel._client = mock_ilink_client

        parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
            TextContent(type=ContentType.TEXT, text="World"),
        ]

        await weixin_channel.send_content_parts(
            to_handle="weixin:user123",
            parts=parts,
            meta={"weixin_context_token": "ctx_token"},
        )

        mock_ilink_client.send_text.assert_called_once()
        call_args = mock_ilink_client.send_text.call_args
        assert call_args[0][0] == "user123"
        assert "Hello" in call_args[0][1]
        assert "World" in call_args[0][1]

    async def test_send_content_parts_with_prefix(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should include bot_prefix in message."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        weixin_channel._client = mock_ilink_client

        parts = [TextContent(type=ContentType.TEXT, text="Message")]

        await weixin_channel.send_content_parts(
            to_handle="weixin:user123",
            parts=parts,
            meta={
                "weixin_context_token": "ctx_token",
                "bot_prefix": "[Prefix]",
            },
        )

        call_args = mock_ilink_client.send_text.call_args
        assert "[Prefix]" in call_args[0][1]
        assert "Message" in call_args[0][1]

    async def test_send_content_parts_disabled_channel(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should do nothing when channel is disabled."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        weixin_channel.enabled = False
        weixin_channel._client = mock_ilink_client

        parts = [TextContent(type=ContentType.TEXT, text="Message")]

        await weixin_channel.send_content_parts(
            to_handle="weixin:user123",
            parts=parts,
            meta={},
        )

        mock_ilink_client.send_text.assert_not_called()

    async def test_send_content_parts_empty_body_skipped(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should skip sending when body is empty."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        weixin_channel._client = mock_ilink_client

        parts = [TextContent(type=ContentType.TEXT, text="")]

        await weixin_channel.send_content_parts(
            to_handle="weixin:user123",
            parts=parts,
            meta={"weixin_context_token": "ctx_token"},
        )

        mock_ilink_client.send_text.assert_not_called()

    async def test_send_content_parts_no_to_user_id(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should do nothing when to_user_id cannot be resolved."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        weixin_channel._client = mock_ilink_client

        parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        await weixin_channel.send_content_parts(
            to_handle="",
            parts=parts,
            meta={},
        )

        mock_ilink_client.send_text.assert_not_called()

    async def test_send_proactive_message(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Successfully send proactive message."""
        weixin_channel._client = mock_ilink_client

        await weixin_channel.send(
            to_handle="weixin:user123",
            text="Proactive message",
            meta={"weixin_context_token": "ctx_token"},
        )

        # Verify send_text was called with correct user_id and message text
        mock_ilink_client.send_text.assert_called_once()
        call_args = mock_ilink_client.send_text.call_args[0]
        assert call_args[0] == "user123"  # user_id
        assert (
            "Proactive message" in call_args[1]
        )  # text includes message (may have prefix)
        assert call_args[2] == "ctx_token"  # context_token

    async def test_send_with_prefix(self, weixin_channel, mock_ilink_client):
        """Should include prefix in proactive message."""
        weixin_channel._client = mock_ilink_client

        await weixin_channel.send(
            to_handle="weixin:user123",
            text="Message",
            meta={"weixin_context_token": "ctx_token", "bot_prefix": "[Bot]"},
        )

        call_args = mock_ilink_client.send_text.call_args
        assert "[Bot]" in call_args[0][1]

    async def test_send_disabled_channel(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should do nothing when channel is disabled."""
        weixin_channel.enabled = False
        weixin_channel._client = mock_ilink_client

        await weixin_channel.send(
            to_handle="weixin:user123",
            text="Message",
            meta={},
        )

        mock_ilink_client.send_text.assert_not_called()


# =============================================================================
# P1: Media Download
# =============================================================================


@pytest.mark.asyncio
class TestWeixinMediaDownload:
    """Tests for media download functionality."""

    async def test_download_media_success(
        self,
        weixin_channel,
        mock_ilink_client,
        temp_media_dir,
    ):
        """Successfully download media file."""
        weixin_channel._client = mock_ilink_client

        result = await weixin_channel._download_media(
            client=mock_ilink_client,
            url="",
            aes_key="test_key",
            filename_hint="image.jpg",
            encrypt_query_param="encrypted_param_123",
        )

        assert result is not None
        assert "weixin_" in result
        assert "image.jpg" in result
        mock_ilink_client.download_media.assert_called_once()

    async def test_download_media_no_encrypt_param(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Download media even without encrypt_query_param."""
        weixin_channel._client = mock_ilink_client

        result = await weixin_channel._download_media(
            client=mock_ilink_client,
            url="http://example.com/file.jpg",
            aes_key="",
            filename_hint="image.jpg",
            encrypt_query_param="",
        )

        # The code doesn't check for empty encrypt_query_param
        # It proceeds to download and returns the file path
        assert result is not None
        assert "weixin_" in result

    async def test_download_media_exception_handling(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should handle download exception gracefully."""
        mock_ilink_client.download_media = AsyncMock(
            side_effect=Exception("Download failed"),
        )
        weixin_channel._client = mock_ilink_client

        result = await weixin_channel._download_media(
            client=mock_ilink_client,
            url="",
            aes_key="test_key",
            filename_hint="image.jpg",
            encrypt_query_param="encrypted_param",
        )

        assert result is None


# =============================================================================
# P1: QR Code Login
# =============================================================================


@pytest.mark.asyncio
class TestWeixinQRCodeLogin:
    """Tests for QR code login functionality."""

    async def test_do_qrcode_login_success(
        self,
        weixin_channel,
        mock_ilink_client,
        temp_token_dir,
    ):
        """Successfully complete QR code login."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._bot_token_file = temp_token_dir / "weixin_bot_token"

        result = await weixin_channel._do_qrcode_login()

        assert result is True
        assert weixin_channel.bot_token == "new_token_123"
        mock_ilink_client.get_bot_qrcode.assert_called_once()
        mock_ilink_client.wait_for_login.assert_called_once_with(
            "qr_code_string",
        )

        # Verify token was saved
        assert weixin_channel._bot_token_file.exists()
        assert weixin_channel._bot_token_file.read_text() == "new_token_123"

    async def test_do_qrcode_login_no_client(self, weixin_channel):
        """Should return False when no client available."""
        weixin_channel._client = None

        result = await weixin_channel._do_qrcode_login()

        assert result is False

    async def test_do_qrcode_login_exception(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Should handle login exception gracefully."""
        mock_ilink_client.get_bot_qrcode = AsyncMock(
            side_effect=Exception("Network error"),
        )
        weixin_channel._client = mock_ilink_client

        result = await weixin_channel._do_qrcode_login()

        assert result is False


# =============================================================================
# P1: Inbound Message Handling
# =============================================================================


@pytest.mark.asyncio
class TestWeixinOnMessage:
    """Tests for _on_message handler."""

    async def test_on_message_text_only(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Handle text message correctly."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "user123",
            "to_user_id": "bot123",
            "context_token": "ctx_token_123",
            "group_id": "",
            "message_type": 1,
            "msg_id": "msg123",
            "item_list": [
                {"type": 1, "text_item": {"text": "Hello World"}},
            ],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        assert weixin_channel._enqueue.called
        call_args = weixin_channel._enqueue.call_args[0][0]
        assert call_args["sender_id"] == "user123"

    async def test_on_message_skip_non_user_message(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Skip non-user messages (message_type != 1)."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "user123",
            "message_type": 2,  # Not user message
            "item_list": [],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        weixin_channel._enqueue.assert_not_called()

    async def test_on_message_skip_duplicate(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Skip duplicate messages."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "user123",
            "context_token": "same_token",
            "message_type": 1,
            "item_list": [{"type": 1, "text_item": {"text": "Hello"}}],
        }

        # First message
        await weixin_channel._on_message(msg, mock_ilink_client)
        assert weixin_channel._enqueue.call_count == 1

        # Duplicate message
        await weixin_channel._on_message(msg, mock_ilink_client)
        # Should still be 1 (duplicate skipped)
        assert weixin_channel._enqueue.call_count == 1

    async def test_on_message_group_chat(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Handle group chat message correctly."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "user123",
            "to_user_id": "bot123",
            "context_token": "ctx_token_123",
            "group_id": "group456",
            "message_type": 1,
            "item_list": [
                {"type": 1, "text_item": {"text": "Hello Group"}},
            ],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        call_args = weixin_channel._enqueue.call_args[0][0]
        assert call_args["session_id"] == "weixin:group:group456"
        assert call_args["meta"]["is_group"] is True

    async def test_on_message_voice(self, weixin_channel, mock_ilink_client):
        """Handle voice message with ASR text."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "user123",
            "context_token": "ctx_token",
            "message_type": 1,
            "item_list": [
                {
                    "type": 3,
                    "voice_item": {
                        "text_item": {"text": "Voice transcription"},
                    },
                },
            ],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        call_args = weixin_channel._enqueue.call_args[0][0]
        content_parts = call_args["content_parts"]
        assert any(
            "Voice transcription" in str(part) for part in content_parts
        )

    async def test_on_message_image(
        self,
        weixin_channel,
        mock_ilink_client,
        temp_media_dir,
    ):
        """Handle image message."""
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()
        mock_ilink_client.download_media = AsyncMock(
            return_value=b"image_data",
        )

        msg = {
            "from_user_id": "user123",
            "context_token": "ctx_token",
            "message_type": 1,
            "item_list": [
                {
                    "type": 2,
                    "image_item": {
                        "aeskey": "a" * 32,  # 32 hex chars = 16 bytes
                        "media": {"encrypt_query_param": "enc_param_123"},
                    },
                },
            ],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        mock_ilink_client.download_media.assert_called_once()
        assert weixin_channel._enqueue.called

    async def test_on_message_allows_sender(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Allow message from authorized sender."""
        weixin_channel.allow_from = {"user123"}
        weixin_channel.dm_policy = "allowlist"
        weixin_channel._client = mock_ilink_client
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "user123",
            "context_token": "ctx_token",
            "message_type": 1,
            "item_list": [{"type": 1, "text_item": {"text": "Hello"}}],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        weixin_channel._enqueue.assert_called_once()

    async def test_on_message_blocks_unauthorized_sender(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Block message from unauthorized sender."""
        weixin_channel.allow_from = {"authorized_user"}
        weixin_channel.dm_policy = "allowlist"
        weixin_channel.deny_message = "Access denied"
        weixin_channel._client = mock_ilink_client
        weixin_channel._loop = asyncio.new_event_loop()
        weixin_channel._enqueue = MagicMock()

        msg = {
            "from_user_id": "unauthorized_user",
            "context_token": "ctx_token",
            "message_type": 1,
            "item_list": [{"type": 1, "text_item": {"text": "Hello"}}],
        }

        await weixin_channel._on_message(msg, mock_ilink_client)

        weixin_channel._enqueue.assert_not_called()
        weixin_channel._loop.close()


# =============================================================================
# P2: Lifecycle (Start/Stop)
# =============================================================================


@pytest.mark.asyncio
class TestWeixinLifecycle:
    """Tests for channel lifecycle management."""

    async def test_start_disabled_channel(self, weixin_channel):
        """Starting disabled channel should succeed without action."""
        weixin_channel.enabled = False

        # Should not raise
        await weixin_channel.start()

        assert weixin_channel._client is None

    async def test_start_with_existing_token(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Start with existing bot_token should skip QR login."""
        weixin_channel.bot_token = "existing_token"

        with patch(
            "qwenpaw.app.channels.weixin.channel.ILinkClient",
            return_value=mock_ilink_client,
        ):
            await weixin_channel.start()

        # Client may be started multiple times in implementation
        assert mock_ilink_client.start.called
        assert weixin_channel._client is not None
        assert weixin_channel._poll_thread is not None

        # Clean up
        weixin_channel._stop_event.set()
        if weixin_channel._poll_thread:
            weixin_channel._poll_thread.join(timeout=0.1)

    async def test_start_without_token_triggers_qr_login(
        self,
        weixin_channel,
        mock_ilink_client,
        temp_token_dir,
    ):
        """Start without token should trigger QR code login."""
        weixin_channel.bot_token = ""
        weixin_channel._bot_token_file = temp_token_dir / "weixin_bot_token"

        with patch(
            "qwenpaw.app.channels.weixin.channel.ILinkClient",
            return_value=mock_ilink_client,
        ):
            await weixin_channel.start()

        mock_ilink_client.get_bot_qrcode.assert_called_once()
        mock_ilink_client.wait_for_login.assert_called_once()

        # Clean up
        weixin_channel._stop_event.set()
        if weixin_channel._poll_thread:
            weixin_channel._poll_thread.join(timeout=0.1)

    async def test_start_loads_token_from_file(
        self,
        weixin_channel,
        mock_ilink_client,
        temp_token_dir,
    ):
        """Start should load token from file when available."""
        token_file = temp_token_dir / "weixin_bot_token"
        token_file.write_text("file_token_123", encoding="utf-8")

        weixin_channel.bot_token = ""
        weixin_channel._bot_token_file = token_file

        with patch(
            "qwenpaw.app.channels.weixin.channel.ILinkClient",
            return_value=mock_ilink_client,
        ):
            await weixin_channel.start()

        assert weixin_channel.bot_token == "file_token_123"

        # Clean up
        weixin_channel._stop_event.set()
        if weixin_channel._poll_thread:
            weixin_channel._poll_thread.join(timeout=0.1)

    async def test_stop_disabled_channel(self, weixin_channel):
        """Stopping disabled channel should succeed without action."""
        weixin_channel.enabled = False

        # Should not raise
        await weixin_channel.stop()

    async def test_stop_cleans_up_resources(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Stop should clean up all resources."""
        weixin_channel.enabled = True
        weixin_channel._client = mock_ilink_client
        weixin_channel._poll_thread = MagicMock()

        await weixin_channel.stop()

        mock_ilink_client.stop.assert_called_once()
        assert weixin_channel._poll_thread is None
        assert weixin_channel._client is None

    async def test_stop_without_prior_start(self, weixin_channel):
        """Stopping without prior start should succeed."""
        # Should not raise
        await weixin_channel.stop()


# =============================================================================
# P2: Allowlist Check
# =============================================================================


class TestWeixinAllowlist:
    """Tests for _check_allowlist method."""

    def test_check_allowlist_open_policy(self, weixin_channel):
        """Open policy should allow all users."""
        weixin_channel.dm_policy = "open"

        allowed, error = weixin_channel._check_allowlist("any_user", False)

        assert allowed is True
        assert error is None

    def test_check_allowlist_group_open_policy(self, weixin_channel):
        """Group open policy should allow all groups."""
        weixin_channel.group_policy = "open"

        allowed, error = weixin_channel._check_allowlist("any_group", True)

        assert allowed is True
        assert error is None

    def test_check_allowlist_dm_allowlist_authorized(self, weixin_channel):
        """DM allowlist should allow authorized users."""
        weixin_channel.dm_policy = "allowlist"
        weixin_channel.allow_from = {"user123"}

        allowed, error = weixin_channel._check_allowlist("user123", False)

        assert allowed is True
        assert error is None

    def test_check_allowlist_dm_allowlist_unauthorized(self, weixin_channel):
        """DM allowlist should block unauthorized users."""
        weixin_channel.dm_policy = "allowlist"
        weixin_channel.allow_from = {"other_user"}
        weixin_channel.deny_message = "Custom denial"

        allowed, error = weixin_channel._check_allowlist("user123", False)

        assert allowed is False
        assert error == "Custom denial"

    def test_check_allowlist_dm_default_deny_message(self, weixin_channel):
        """Should use default deny message when not configured."""
        weixin_channel.dm_policy = "allowlist"
        weixin_channel.allow_from = set()
        weixin_channel.deny_message = ""

        allowed, error = weixin_channel._check_allowlist("user123", False)

        assert allowed is False
        assert "not authorized" in error
        assert "user123" in error

    def test_check_allowlist_group_allowlist(self, weixin_channel):
        """Group allowlist should use different deny message."""
        weixin_channel.group_policy = "allowlist"
        weixin_channel.allow_from = set()
        weixin_channel.deny_message = ""

        allowed, error = weixin_channel._check_allowlist("group123", True)

        assert allowed is False
        assert "only available to authorized users" in error


# =============================================================================
# P2: Edge Cases
# =============================================================================


@pytest.mark.asyncio
class TestWeixinEdgeCases:
    """Additional edge case tests."""

    async def test_send_content_parts_long_text_splitting(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Long text should be split into chunks."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        weixin_channel._client = mock_ilink_client

        # Create very long text
        long_text = "A" * 5000
        parts = [TextContent(type=ContentType.TEXT, text=long_text)]

        await weixin_channel.send_content_parts(
            to_handle="weixin:user123",
            parts=parts,
            meta={"weixin_context_token": "ctx_token"},
        )

        # Should call send_text multiple times for chunks
        assert mock_ilink_client.send_text.call_count > 1

    async def test_download_media_invalid_filename(
        self,
        weixin_channel,
        mock_ilink_client,
        temp_media_dir,
    ):
        """Should sanitize invalid filename characters."""
        mock_ilink_client.download_media = AsyncMock(return_value=b"data")
        weixin_channel._client = mock_ilink_client

        result = await weixin_channel._download_media(
            client=mock_ilink_client,
            url="",
            aes_key="key",
            filename_hint="file<name>with:invalid|chars*.jpg",
            encrypt_query_param="param",
        )

        assert result is not None
        # Invalid chars should be stripped
        assert "<" not in result
        assert ">" not in result

    async def test_poll_loop_exception_handling(
        self,
        weixin_channel,
        mock_ilink_client,
    ):
        """Poll loop should handle exceptions gracefully."""
        mock_ilink_client.getupdates = AsyncMock(
            side_effect=Exception("Network error"),
        )
        weixin_channel._client = mock_ilink_client
        weixin_channel._stop_event.set()  # Stop after one iteration

        # Should not raise despite exception
        try:
            await weixin_channel._poll_loop_async()
        except Exception:
            pytest.fail("_poll_loop_async should handle exceptions gracefully")

    def test_build_agent_request_with_varied_content(self, weixin_channel):
        """Should handle different content types in build_agent_request."""
        from qwenpaw.app.channels.base import ImageContent, ContentType

        payload = {
            "channel_id": "wechat",
            "sender_id": "user123",
            "content_parts": [
                ImageContent(
                    type=ContentType.IMAGE,
                    image_url="http://img.jpg",
                ),
            ],
            "meta": {},
        }

        request = weixin_channel.build_agent_request_from_native(payload)

        assert request.user_id == "user123"
        assert len(request.input) == 1
