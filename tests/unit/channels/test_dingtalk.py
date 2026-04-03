# -*- coding: utf-8 -*-
"""
DingTalk Channel Unit Tests

Comprehensive unit tests for DingTalkChannel covering:
- Initialization and configuration
- Session webhook management (storage/retrieval/expiry)
- Token caching mechanism
- Message deduplication (thread safety)
- Send methods (webhook, Open API, AI Card)
- Utility functions

Test Patterns:
- Uses MockAiohttpSession for HTTP request mocking
- Tests based on CHAN-D02 (webhook expiry), CHAN-D04 (file receiving)
- Covers complex internal logic not covered by contract tests

Run:
    pytest tests/unit/channels/test_dingtalk.py -v
    pytest tests/unit/channels/test_dingtalk.py::TestDingTalkSessionWebhook -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=broad-exception-raised,using-constant-test
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures.channels.mock_http import (
    MockAiohttpSession,
    MockAiohttpResponse,
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
def temp_media_dir(tmp_path) -> Path:
    """Temporary directory for media files."""
    media_dir = tmp_path / ".copaw" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


@pytest.fixture
def temp_workspace_dir(tmp_path) -> Path:
    """Temporary workspace directory."""
    workspace = tmp_path / ".copaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def dingtalk_channel(
    mock_process_handler,
    temp_media_dir,
) -> Generator:
    """Create a DingTalkChannel instance for testing."""
    from copaw.app.channels.dingtalk.channel import DingTalkChannel

    channel = DingTalkChannel(
        process=mock_process_handler,
        enabled=True,
        client_id="test_client_id",
        client_secret="test_client_secret",
        bot_prefix="[TestBot] ",
        media_dir=str(temp_media_dir),
        show_tool_details=False,
        filter_tool_messages=True,
    )
    yield channel


@pytest.fixture
def dingtalk_channel_with_workspace(
    mock_process_handler,
    temp_workspace_dir,
) -> Generator:
    """Create a DingTalkChannel with workspace for testing."""
    from copaw.app.channels.dingtalk.channel import DingTalkChannel

    channel = DingTalkChannel(
        process=mock_process_handler,
        enabled=True,
        client_id="test_client_id",
        client_secret="test_client_secret",
        bot_prefix="[TestBot] ",
        workspace_dir=temp_workspace_dir,
        show_tool_details=False,
        filter_tool_messages=True,
    )
    yield channel


@pytest.fixture
def mock_http_session() -> MockAiohttpSession:
    """Create a mock aiohttp session."""
    return MockAiohttpSession()


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestDingTalkChannelInit:
    """
    Tests for DingTalkChannel initialization and factory methods.
    Verifies correct storage of configuration parameters.
    """

    def test_init_stores_basic_config(
        self, mock_process_handler, temp_media_dir
    ):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        channel = DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="my_client_id",
            client_secret="my_client_secret",
            bot_prefix="[Bot] ",
            message_type="text",
            media_dir=str(temp_media_dir),
        )

        assert channel.enabled is True
        assert channel.client_id == "my_client_id"
        assert channel.client_secret == "my_client_secret"
        assert channel.bot_prefix == "[Bot] "
        assert channel.message_type == "text"
        assert channel.channel == "dingtalk"

    def test_init_stores_advanced_config(
        self, mock_process_handler, temp_media_dir
    ):
        """Constructor should store advanced configuration parameters."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        channel = DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_id",
            client_secret="test_secret",
            bot_prefix="",
            card_template_id="template_123",
            card_template_key="my_key",
            robot_code="robot_456",
            require_mention=True,
            card_auto_layout=True,
        )

        assert channel.card_template_id == "template_123"
        assert channel.card_template_key == "my_key"
        assert channel.robot_code == "robot_456"
        assert channel.require_mention is True
        assert channel.card_auto_layout is True

    def test_init_creates_required_data_structures(self, mock_process_handler):
        """Constructor should initialize required internal data structures."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        channel = DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_id",
            client_secret="test_secret",
            bot_prefix="",
        )

        # Session webhook store
        assert hasattr(channel, "_session_webhook_store")
        assert isinstance(channel._session_webhook_store, dict)

        # Processing message IDs set
        assert hasattr(channel, "_processing_message_ids")
        assert isinstance(channel._processing_message_ids, set)

        # Token cache
        assert hasattr(channel, "_token_value")
        assert channel._token_value is None
        assert hasattr(channel, "_token_expires_at")
        assert channel._token_expires_at == 0.0

    def test_init_creates_locks(self, mock_process_handler):
        """Constructor should create required locks for thread safety."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        channel = DingTalkChannel(
            process=mock_process_handler,
            enabled=True,
            client_id="test_id",
            client_secret="test_secret",
            bot_prefix="",
        )

        # Session webhook lock
        assert hasattr(channel, "_session_webhook_lock")
        assert isinstance(channel._session_webhook_lock, asyncio.Lock)

        # Token lock
        assert hasattr(channel, "_token_lock")
        assert isinstance(channel._token_lock, asyncio.Lock)

        # Processing message IDs lock
        assert hasattr(channel, "_processing_message_ids_lock")
        lock_type = type(channel._processing_message_ids_lock).__name__
        assert "lock" in lock_type.lower()

    def test_channel_type_is_dingtalk(self, dingtalk_channel):
        """Channel type must be 'dingtalk'."""
        assert dingtalk_channel.channel == "dingtalk"


class TestDingTalkChannelFromEnv:
    """Tests for from_env factory method."""

    def test_from_env_reads_basic_env_vars(
        self, mock_process_handler, monkeypatch
    ):
        """from_env should read basic environment variables."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        monkeypatch.setenv("DINGTALK_CHANNEL_ENABLED", "0")
        monkeypatch.setenv("DINGTALK_CLIENT_ID", "env_client_id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "env_client_secret")
        monkeypatch.setenv("DINGTALK_BOT_PREFIX", "[EnvBot] ")

        channel = DingTalkChannel.from_env(mock_process_handler)

        assert channel.enabled is False
        assert channel.client_id == "env_client_id"
        assert channel.client_secret == "env_client_secret"
        assert channel.bot_prefix == "[EnvBot] "

    def test_from_env_reads_advanced_env_vars(
        self, mock_process_handler, monkeypatch
    ):
        """from_env should read advanced environment variables."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        monkeypatch.setenv("DINGTALK_CLIENT_ID", "test_id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "test_secret")
        monkeypatch.setenv("DINGTALK_MESSAGE_TYPE", "text")
        monkeypatch.setenv("DINGTALK_CARD_TEMPLATE_ID", "template_env")
        monkeypatch.setenv("DINGTALK_CARD_TEMPLATE_KEY", "content_env")
        monkeypatch.setenv("DINGTALK_ROBOT_CODE", "robot_env")
        monkeypatch.setenv("DINGTALK_REQUIRE_MENTION", "1")
        monkeypatch.setenv("DINGTALK_CARD_AUTO_LAYOUT", "1")

        channel = DingTalkChannel.from_env(mock_process_handler)

        assert channel.message_type == "text"
        assert channel.card_template_id == "template_env"
        assert channel.card_template_key == "content_env"
        assert channel.robot_code == "robot_env"
        assert channel.require_mention is True
        assert channel.card_auto_layout is True

    def test_from_env_allow_from_parsing(
        self, mock_process_handler, monkeypatch
    ):
        """from_env should parse DINGTALK_ALLOW_FROM correctly."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        monkeypatch.setenv("DINGTALK_CLIENT_ID", "test_id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "test_secret")
        monkeypatch.setenv("DINGTALK_ALLOW_FROM", "user1,user2,user3")

        channel = DingTalkChannel.from_env(mock_process_handler)

        assert "user1" in channel.allow_from
        assert "user2" in channel.allow_from
        assert "user3" in channel.allow_from

    def test_from_env_allow_from_empty(
        self, mock_process_handler, monkeypatch
    ):
        """from_env should handle empty DINGTALK_ALLOW_FROM."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        monkeypatch.setenv("DINGTALK_CLIENT_ID", "test_id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "test_secret")
        monkeypatch.setenv("DINGTALK_ALLOW_FROM", "")

        channel = DingTalkChannel.from_env(mock_process_handler)

        assert channel.allow_from == set()

    def test_from_env_defaults(self, mock_process_handler, monkeypatch):
        """from_env should use sensible defaults."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel

        monkeypatch.setenv("DINGTALK_CLIENT_ID", "test_id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "test_secret")
        monkeypatch.delenv("DINGTALK_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("DINGTALK_BOT_PREFIX", raising=False)
        monkeypatch.delenv("DINGTALK_REQUIRE_MENTION", raising=False)

        channel = DingTalkChannel.from_env(mock_process_handler)

        assert channel.enabled is True  # Default enabled
        assert channel.bot_prefix == ""  # Default empty
        assert channel.require_mention is False  # Default False


class TestDingTalkChannelFromConfig:
    """Tests for from_config factory method."""

    def test_from_config_uses_config_values(self, mock_process_handler):
        """from_config should use values from config object."""
        from copaw.app.channels.dingtalk.channel import DingTalkChannel
        from copaw.config.config import DingTalkConfig

        config = DingTalkConfig(
            enabled=False,
            client_id="config_client_id",
            client_secret="config_client_secret",
            bot_prefix="[ConfigBot] ",
            message_type="text",
            dm_policy="allowlist",  # Valid values: 'open' or 'allowlist'
            group_policy="allowlist",
            require_mention=True,
        )

        channel = DingTalkChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is False
        assert channel.client_id == "config_client_id"
        assert channel.client_secret == "config_client_secret"
        assert channel.bot_prefix == "[ConfigBot] "
        assert channel.message_type == "text"
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"
        assert channel.require_mention is True


# =============================================================================
# P1: Session Webhook Management (Critical for CHAN-D02)
# =============================================================================


@pytest.mark.asyncio
class TestDingTalkSessionWebhook:
    """
    Tests for session webhook storage and retrieval.

    CHAN-D02: 钉钉 sessionWebhook 过期后定时推送
    - sessionWebhook has an expiry time
    - System should refresh/re-obtain valid sessionWebhook
    - Webhooks should be persisted to disk for cron jobs
    """

    async def test_save_session_webhook_stores_in_memory(
        self, dingtalk_channel
    ):
        """Saving webhook should store it in memory."""
        await dingtalk_channel._save_session_webhook(
            webhook_key="dingtalk:sw:test123",
            session_webhook="https://oapi.dingtalk.com/robot/send?session=abc",
            expired_time=1234567890000,
            conversation_id="conv_test",
            conversation_type="group",
            sender_staff_id="staff123",
        )

        assert "dingtalk:sw:test123" in dingtalk_channel._session_webhook_store
        entry = dingtalk_channel._session_webhook_store["dingtalk:sw:test123"]
        assert (
            entry["webhook"]
            == "https://oapi.dingtalk.com/robot/send?session=abc"
        )
        assert entry["expired_time"] == 1234567890000
        assert entry["conversation_id"] == "conv_test"
        assert entry["conversation_type"] == "group"
        assert entry["sender_staff_id"] == "staff123"

    async def test_save_session_webhook_persists_to_disk(
        self,
        dingtalk_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Saving webhook should persist to disk for recovery."""
        channel = dingtalk_channel_with_workspace

        await channel._save_session_webhook(
            webhook_key="dingtalk:sw:disktest",
            session_webhook="https://oapi.dingtalk.com/robot/send?session=disk",
            expired_time=9999999999999,
            conversation_id="conv_disk",
        )

        # Check file exists
        store_path = temp_workspace_dir / "dingtalk_session_webhooks.json"
        assert store_path.exists()

        # Verify content
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "dingtalk:sw:disktest" in data
        entry = data["dingtalk:sw:disktest"]
        assert (
            entry["webhook"]
            == "https://oapi.dingtalk.com/robot/send?session=disk"
        )
        assert entry["conversation_id"] == "conv_disk"

    async def test_load_session_webhook_from_memory(self, dingtalk_channel):
        """Loading webhook should first check memory."""
        # Pre-populate memory store
        dingtalk_channel._session_webhook_store["dingtalk:sw:memtest"] = {
            "webhook": "http://memory.webhook",
            "expired_time": 9999999999999,
        }

        result = await dingtalk_channel._load_session_webhook(
            "dingtalk:sw:memtest"
        )

        assert result == "http://memory.webhook"

    async def test_load_session_webhook_from_disk(
        self,
        dingtalk_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Loading webhook should fallback to disk if not in memory."""
        channel = dingtalk_channel_with_workspace

        # Create file manually
        store_path = temp_workspace_dir / "dingtalk_session_webhooks.json"
        data = {
            "dingtalk:sw:diskload": {
                "webhook": "http://disk.webhook",
                "expired_time": 9999999999999,
                "conversation_id": "conv_from_disk",
            },
        }
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = await channel._load_session_webhook("dingtalk:sw:diskload")

        assert result == "http://disk.webhook"
        # Should also be loaded into memory
        assert "dingtalk:sw:diskload" in channel._session_webhook_store

    async def test_load_session_webhook_expired_returns_none(
        self, dingtalk_channel
    ):
        """Loading expired webhook should return None."""
        # Create webhook that expired 1 hour ago
        past_time = int((time.time() - 3600) * 1000)
        dingtalk_channel._session_webhook_store["dingtalk:sw:expired"] = {
            "webhook": "http://expired.webhook",
            "expired_time": past_time,
        }

        result = await dingtalk_channel._load_session_webhook(
            "dingtalk:sw:expired"
        )

        assert result is None

    async def test_load_session_webhook_not_found_returns_none(
        self, dingtalk_channel
    ):
        """Loading non-existent webhook should return None."""
        result = await dingtalk_channel._load_session_webhook(
            "dingtalk:sw:nonexistent"
        )

        assert result is None

    async def test_load_session_webhook_empty_key_returns_none(
        self, dingtalk_channel
    ):
        """Loading with empty key should return None."""
        result = await dingtalk_channel._load_session_webhook("")

        assert result is None

    def test_is_webhook_expired_with_past_time(self, dingtalk_channel):
        """Webhook with past expiry time should be considered expired."""
        past_time = int((time.time() - 3600) * 1000)  # 1 hour ago
        entry = {"webhook": "http://test", "expired_time": past_time}

        result = dingtalk_channel._is_webhook_expired(entry)

        assert result is True

    def test_is_webhook_expired_with_future_time(self, dingtalk_channel):
        """Webhook with future expiry time should not be expired."""
        future_time = int((time.time() + 3600) * 1000)  # 1 hour from now
        entry = {"webhook": "http://test", "expired_time": future_time}

        result = dingtalk_channel._is_webhook_expired(entry)

        assert result is False

    def test_is_webhook_expired_with_safety_margin(self, dingtalk_channel):
        """Webhook near expiry (within safety margin) should be expired."""
        # 5 minutes from now, within default 10-minute safety margin
        near_future = int((time.time() + 300) * 1000)
        entry = {"webhook": "http://test", "expired_time": near_future}

        result = dingtalk_channel._is_webhook_expired(entry)

        assert result is True

    def test_is_webhook_expired_no_expiry_time(self, dingtalk_channel):
        """Webhook without expiry time should not be considered expired."""
        entry = {"webhook": "http://test"}

        result = dingtalk_channel._is_webhook_expired(entry)

        assert result is False

    async def test_save_session_webhook_empty_key_skips(
        self, dingtalk_channel
    ):
        """Saving with empty key should be skipped."""
        await dingtalk_channel._save_session_webhook(
            webhook_key="",
            session_webhook="http://test",
        )

        assert "" not in dingtalk_channel._session_webhook_store

    async def test_save_session_webhook_empty_webhook_skips(
        self, dingtalk_channel
    ):
        """Saving with empty webhook should be skipped."""
        await dingtalk_channel._save_session_webhook(
            webhook_key="key",
            session_webhook="",
        )

        assert "key" not in dingtalk_channel._session_webhook_store


# =============================================================================
# P1: Token Caching (HTTP Mock tests)
# =============================================================================


@pytest.mark.asyncio
class TestDingTalkTokenCache:
    """
    Tests for access token caching mechanism.

    DingTalk access tokens should be cached and only refreshed when expired.
    Uses asyncio loop time (monotonic) not wall clock time.
    """

    async def test_get_access_token_fetches_when_empty(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Should fetch new token when cache is empty."""
        from copaw.app.channels.dingtalk.constants import (
            DINGTALK_TOKEN_TTL_SECONDS,
        )

        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={
                "accessToken": "new_token_123",
                "expireIn": 7200,
            },
        )

        token = await dingtalk_channel._get_access_token()

        assert token == "new_token_123"
        assert dingtalk_channel._token_value == "new_token_123"
        # Token expires in the future (uses loop time + TTL)
        assert (
            dingtalk_channel._token_expires_at
            > asyncio.get_running_loop().time()
        )
        assert dingtalk_channel._token_expires_at <= (
            asyncio.get_running_loop().time() + DINGTALK_TOKEN_TTL_SECONDS
        )

    async def test_get_access_token_uses_cache_when_valid(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Should use cached token when not expired."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._token_value = "cached_token"
        dingtalk_channel._token_expires_at = (
            asyncio.get_running_loop().time() + 3600
        )  # Valid for 1 hour

        token = await dingtalk_channel._get_access_token()

        assert token == "cached_token"
        assert mock_http_session.call_count == 0  # No HTTP call made

    async def test_get_access_token_refreshes_when_expired(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Should fetch new token when cached token is expired."""
        dingtalk_channel._http = mock_http_session
        dingtalk_channel._token_value = "old_token"
        dingtalk_channel._token_expires_at = (
            asyncio.get_running_loop().time() - 100
        )  # Expired

        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={
                "accessToken": "refreshed_token",
                "expireIn": 7200,
            },
        )

        token = await dingtalk_channel._get_access_token()

        assert token == "refreshed_token"
        assert dingtalk_channel._token_value == "refreshed_token"

    async def test_get_access_token_handles_api_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Should handle API error gracefully."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={
                "errcode": 40001,
                "errmsg": "invalid credential",
            },
        )

        with pytest.raises(RuntimeError, match="accessToken not found"):
            await dingtalk_channel._get_access_token()

    async def test_get_access_token_thread_safe(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Token fetching should be thread-safe (using asyncio.Lock)."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={
                "accessToken": "token_123",
                "expireIn": 7200,
            },
        )

        # Simulate concurrent calls
        tokens = await asyncio.gather(
            dingtalk_channel._get_access_token(),
            dingtalk_channel._get_access_token(),
            dingtalk_channel._get_access_token(),
        )

        # All should get the same token
        assert all(t == "token_123" for t in tokens)


# =============================================================================
# P1: Message Deduplication (Thread Safety)
# =============================================================================


class TestDingTalkMessageDedup:
    """
    Tests for message deduplication mechanism.

    DingTalk can deliver the same message multiple times.
    We track in-flight message IDs to prevent double-processing.
    """

    def test_try_accept_message_accepts_new_message(self, dingtalk_channel):
        """Should accept message with new ID."""
        result = dingtalk_channel._try_accept_message("msg_123")

        assert result is True
        assert "msg_123" in dingtalk_channel._processing_message_ids

    def test_try_accept_message_rejects_duplicate(self, dingtalk_channel):
        """Should reject message with duplicate ID."""
        # First accept
        dingtalk_channel._try_accept_message("msg_dup")

        # Second accept should fail
        result = dingtalk_channel._try_accept_message("msg_dup")

        assert result is False

    def test_try_accept_message_allows_empty_id(self, dingtalk_channel):
        """Empty message ID should be accepted but not tracked."""
        result = dingtalk_channel._try_accept_message("")

        assert result is True
        assert "" not in dingtalk_channel._processing_message_ids

    def test_release_message_ids_removes_from_set(self, dingtalk_channel):
        """Should remove message ID from tracking set."""
        dingtalk_channel._try_accept_message("msg_release")
        assert "msg_release" in dingtalk_channel._processing_message_ids

        dingtalk_channel._release_message_ids(["msg_release"])

        assert "msg_release" not in dingtalk_channel._processing_message_ids

    def test_release_message_ids_handles_empty_list(self, dingtalk_channel):
        """Should handle empty list gracefully."""
        initial_count = len(dingtalk_channel._processing_message_ids)
        dingtalk_channel._release_message_ids([])

        assert len(dingtalk_channel._processing_message_ids) == initial_count

    def test_release_message_ids_handles_unknown_ids(self, dingtalk_channel):
        """Should handle IDs not in set gracefully."""
        # Should not raise
        dingtalk_channel._release_message_ids(["unknown_id"])

    def test_try_accept_message_is_thread_safe(self, dingtalk_channel):
        """Deduplication should be thread-safe."""
        accepted_count = [0]
        rejected_count = [0]

        def try_accept():
            for i in range(100):
                msg_id = f"batch_msg_{i % 10}"  # 10 unique IDs, 10 times each
                if dingtalk_channel._try_accept_message(msg_id):
                    accepted_count[0] += 1
                else:
                    rejected_count[0] += 1

        threads = [threading.Thread(target=try_accept) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 10 accepted (one for each unique ID)
        # and 490 rejected (99 duplicates per ID * 5 threads, but some race)
        assert accepted_count[0] == 10


# =============================================================================
# P1: Send Methods (HTTP Mock Tests)
# =============================================================================


@pytest.mark.asyncio
class TestDingTalkSendMethods:
    """
    Tests for send methods using HTTP mocking.

    Covers:
    - send() method
    - _send_via_session_webhook()
    - _send_via_open_api()
    - _send_payload_via_session_webhook()
    """

    async def test_send_via_session_webhook_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Successfully send via session webhook."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        result = await dingtalk_channel._send_via_session_webhook(
            session_webhook="https://oapi.dingtalk.com/robot/send?session=abc",
            body="Hello from test",
            bot_prefix="[Bot]",
        )

        assert result is True
        assert mock_http_session.call_count == 1

    async def test_send_via_session_webhook_api_error(
        self,
        dingtalk_channel,
    ):
        """Handle API error response with non-zero errcode - patch at method level."""

        # Mock the response
        class MockResponse:
            status = 200

            async def text(self):
                return '{"errcode": 400001, "errmsg": "invalid session"}'

        class MockClientSession:
            async def __aenter__(self):
                return MockResponse()

            async def __aexit__(self, *args):
                pass

        dingtalk_channel._http = MagicMock()
        dingtalk_channel._http.post = MockClientSession

        result = await dingtalk_channel._send_payload_via_session_webhook(
            session_webhook="https://oapi.dingtalk.com/robot/send?session=abc",
            payload={"msgtype": "text", "text": {"content": "Hello"}},
        )

        assert result is False

    async def test_send_via_session_webhook_http_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle HTTP error response."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=500,
            response_text="Internal Server Error",
        )

        result = await dingtalk_channel._send_via_session_webhook(
            session_webhook="https://oapi.dingtalk.com/robot/send?session=abc",
            body="Hello",
        )

        assert result is False

    async def test_send_payload_via_session_webhook_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send custom payload via session webhook."""
        dingtalk_channel._http = mock_http_session
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/robot/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": "Test", "text": "Hello"},
        }
        result = await dingtalk_channel._send_payload_via_session_webhook(
            session_webhook="https://oapi.dingtalk.com/robot/send?session=abc",
            payload=payload,
        )

        assert result is True

    async def test_send_via_open_api_group_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send via Open API for group chat."""
        dingtalk_channel._http = mock_http_session

        # First call: get access token
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )

        # Second call: send group message
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/robot/groupMessages/send",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        result = await dingtalk_channel._send_via_open_api(
            body="Hello group",
            conversation_id="cid_group_123",
            conversation_type="group",
            sender_staff_id="",
        )

        assert result is True

    async def test_send_via_open_api_dm_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Send via Open API for direct message."""
        dingtalk_channel._http = mock_http_session

        # First call: get access token
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )

        # Second call: send DM
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend",
            response_status=200,
            response_json={"errcode": 0, "errmsg": "ok"},
        )

        result = await dingtalk_channel._send_via_open_api(
            body="Hello DM",
            conversation_id="cid_dm_123",
            conversation_type="single",
            sender_staff_id="staff_123",
        )

        assert result is True

    async def test_send_via_open_api_dm_no_staff_id_fails(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """DM should fail without sender_staff_id."""
        dingtalk_channel._http = mock_http_session

        # Token is fetched first, then staff_id check happens
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )

        result = await dingtalk_channel._send_via_open_api(
            body="Hello DM",
            conversation_id="cid_dm_123",
            conversation_type="single",
            sender_staff_id="",  # Empty staff ID
        )

        assert result is False

    async def test_send_disabled_channel_does_nothing(self, dingtalk_channel):
        """Send should return early when channel is disabled."""
        dingtalk_channel.enabled = False

        result = await dingtalk_channel.send(
            to_handle="user123",
            text="Hello",
            meta={},
        )

        # Should not raise, just return
        assert result is None


# =============================================================================
# P2: resolve_session_id and Routing
# =============================================================================


class TestDingTalkResolveSession:
    """Tests for session resolution and routing."""

    def test_resolve_session_id_with_conversation_id(self, dingtalk_channel):
        """resolve_session_id should use conversation_id when available."""
        result = dingtalk_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={"conversation_id": "cid_abc_xyz"},
        )

        # Takes last 8 chars: DINGTALK_SESSION_ID_SUFFIX_LEN = 8
        assert result == "_abc_xyz"

    def test_resolve_session_id_without_conversation_id(
        self, dingtalk_channel
    ):
        """resolve_session_id should fallback to sender_id format."""
        result = dingtalk_channel.resolve_session_id(
            sender_id="user456",
            channel_meta={},
        )

        assert result == "dingtalk:user456"

    def test_to_handle_from_target_formats_correctly(self, dingtalk_channel):
        """to_handle_from_target should format handle with session_id."""
        result = dingtalk_channel.to_handle_from_target(
            user_id="user123",
            session_id="sess_abc",
        )

        assert result == "dingtalk:sw:sess_abc"

    def test_route_from_handle_sw(self, dingtalk_channel):
        """_route_from_handle should parse 'dingtalk:sw:' format."""
        result = dingtalk_channel._route_from_handle("dingtalk:sw:abc123")

        assert result == {"webhook_key": "dingtalk:sw:abc123"}

    def test_route_from_handle_webhook(self, dingtalk_channel):
        """_route_from_handle should parse 'dingtalk:webhook:' format."""
        result = dingtalk_channel._route_from_handle(
            "dingtalk:webhook:http://webhook.url",
        )

        assert result == {"session_webhook": "http://webhook.url"}

    def test_route_from_handle_direct_url(self, dingtalk_channel):
        """_route_from_handle should accept direct webhook URL."""
        result = dingtalk_channel._route_from_handle(
            "https://oapi.dingtalk.com/robot"
        )

        assert result == {"session_webhook": "https://oapi.dingtalk.com/robot"}

    def test_route_from_handle_empty(self, dingtalk_channel):
        """_route_from_handle should handle empty string."""
        result = dingtalk_channel._route_from_handle("")

        assert result == {}


# =============================================================================
# P2: Open API Fallback (Critical for CHAN-D02)
# =============================================================================


@pytest.mark.asyncio
class TestDingTalkOpenAPIFallback:
    """
    Tests for Open API fallback when sessionWebhook is expired.

    CHAN-D02: Cron jobs should still work after webhook expires
    """

    async def test_try_open_api_fallback_with_stored_webhook(
        self,
        dingtalk_channel_with_workspace,
        mock_http_session,
    ):
        """Fallback should use stored webhook entry for metadata."""
        channel = dingtalk_channel_with_workspace
        channel._http = mock_http_session

        # Store webhook entry
        channel._session_webhook_store["dingtalk:sw:storedkey"] = {
            "webhook": "http://stored.webhook",
            "conversation_id": "stored_conv_id",
            "conversation_type": "group",
            "sender_staff_id": "stored_staff",
        }

        # Mock token and send
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/robot/groupMessages/send",
            response_status=200,
            response_json={"errcode": 0},
        )

        result = await channel._try_open_api_fallback(
            text="Fallback message",
            to_handle="dingtalk:sw:storedkey",
            meta={},
        )

        assert result is True

    async def test_try_open_api_fallback_no_conversation_id(
        self,
        dingtalk_channel,
    ):
        """Fallback should fail without conversation_id."""
        result = await dingtalk_channel._try_open_api_fallback(
            text="Test",
            to_handle="dingtalk:sw:unknown",
            meta={},
        )

        assert result is False

    def test_resolve_open_api_params_from_meta(self, dingtalk_channel):
        """Should extract params from meta with priority."""
        meta = {
            "conversation_id": "meta_conv",
            "conversation_type": "meta_type",
            "sender_staff_id": "meta_staff",
        }
        entry = {
            "conversation_id": "entry_conv",
            "conversation_type": "entry_type",
            "sender_staff_id": "entry_staff",
        }

        result = dingtalk_channel._resolve_open_api_params(meta, entry)

        # Meta takes priority
        assert result["conversation_id"] == "meta_conv"
        assert result["conversation_type"] == "meta_type"
        assert result["sender_staff_id"] == "meta_staff"

    def test_resolve_open_api_params_from_entry(self, dingtalk_channel):
        """Should fallback to entry when meta is empty."""
        meta = {}
        entry = {
            "conversation_id": "entry_conv",
            "conversation_type": "entry_type",
            "sender_staff_id": "entry_staff",
        }

        result = dingtalk_channel._resolve_open_api_params(meta, entry)

        assert result["conversation_id"] == "entry_conv"
        assert result["conversation_type"] == "entry_type"
        assert result["sender_staff_id"] == "entry_staff"


# =============================================================================
# P2: Parts to Text Conversion
# =============================================================================


class TestDingTalkPartsToText:
    """Tests for _parts_to_single_text method."""

    def test_parts_to_single_text_with_text(self, dingtalk_channel):
        """Should combine text parts."""
        from copaw.app.channels.base import TextContent, ContentType

        parts = [
            TextContent(type=ContentType.TEXT, text="Hello"),
            TextContent(type=ContentType.TEXT, text="World"),
        ]

        result = dingtalk_channel._parts_to_single_text(parts)

        assert "Hello" in result
        assert "World" in result

    def test_parts_to_single_text_with_prefix(self, dingtalk_channel):
        """Should include bot_prefix."""
        from copaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="Message")]

        result = dingtalk_channel._parts_to_single_text(
            parts,
            bot_prefix="[Bot]",
        )

        assert "[Bot]" in result
        assert "Message" in result

    def test_parts_to_single_text_with_refusal(self, dingtalk_channel):
        """Should handle refusal content."""
        from copaw.app.channels.base import RefusalContent, ContentType

        parts = [RefusalContent(type=ContentType.REFUSAL, refusal="I cannot")]

        result = dingtalk_channel._parts_to_single_text(parts)

        assert "I cannot" in result

    def test_parts_to_single_text_with_image(self, dingtalk_channel):
        """Should format image content."""
        from copaw.app.channels.base import ImageContent, ContentType

        parts = [
            ImageContent(type=ContentType.IMAGE, image_url="http://img.jpg")
        ]

        result = dingtalk_channel._parts_to_single_text(parts)

        assert "[Image:" in result
        assert "http://img.jpg" in result

    def test_parts_to_single_text_empty_list(self, dingtalk_channel):
        """Should handle empty parts list."""
        result = dingtalk_channel._parts_to_single_text([])

        assert result == ""


# =============================================================================
# P2: Session Webhook from Meta
# =============================================================================


class TestDingTalkGetSessionWebhook:
    """Tests for _get_session_webhook method."""

    def test_get_session_webhook_from_meta(self, dingtalk_channel):
        """Should get webhook from meta dict."""
        result = dingtalk_channel._get_session_webhook(
            {"session_webhook": "http://meta.webhook"},
        )

        assert result == "http://meta.webhook"

    def test_get_session_webhook_from_incoming_message(self, dingtalk_channel):
        """Should get webhook from incoming_message object."""
        mock_msg = MagicMock()
        mock_msg.sessionWebhook = "http://msg.webhook"

        result = dingtalk_channel._get_session_webhook(
            {"incoming_message": mock_msg},
        )

        assert result == "http://msg.webhook"

    def test_get_session_webhook_none_meta(self, dingtalk_channel):
        """Should handle None meta."""
        result = dingtalk_channel._get_session_webhook(None)

        assert result is None

    def test_get_session_webhook_empty_meta(self, dingtalk_channel):
        """Should handle empty meta."""
        result = dingtalk_channel._get_session_webhook({})

        assert result is None


# =============================================================================
# P2: Build Agent Request
# =============================================================================


class TestDingTalkBuildAgentRequest:
    """Tests for build_agent_request_from_native method."""

    def test_build_agent_request_creates_request(self, dingtalk_channel):
        """Should create AgentRequest from native payload."""
        from copaw.app.channels.base import TextContent, ContentType

        payload = {
            "channel_id": "dingtalk",
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello")
            ],
            "meta": {"session_webhook": "http://webhook.url"},
        }

        request = dingtalk_channel.build_agent_request_from_native(payload)

        assert request.user_id == "user123"
        assert request.channel == "dingtalk"
        assert len(request.input) == 1


# =============================================================================
# P2: Reply Sync Methods
# =============================================================================


class TestDingTalkReplySync:
    """Tests for _reply_sync and _reply_sync_batch methods."""

    def test_reply_sync_sets_future_result(self, dingtalk_channel):
        """Should set future result."""
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        meta = {"reply_loop": loop, "reply_future": future}

        dingtalk_channel._reply_sync(meta, "reply text")

        # Need to run loop to process callback
        loop.run_until_complete(asyncio.sleep(0.01))

        assert future.done()
        assert future.result() == "reply text"
        loop.close()

    def test_safe_set_future_result_handles_done_future(
        self, dingtalk_channel
    ):
        """Should not error when future is already done."""
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        future.set_result("already set")

        # Should not raise
        dingtalk_channel._safe_set_future_result(future, "new result")

        assert future.result() == "already set"
        loop.close()


# =============================================================================
# P2: Utility Functions
# =============================================================================


class TestDingTalkUtils:
    """Tests for utility functions in utils.py."""

    def test_guess_suffix_from_file_content_pdf(self, tmp_path):
        """Should detect PDF files by magic bytes."""
        from copaw.app.channels.dingtalk.utils import (
            guess_suffix_from_file_content,
        )

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test content")

        result = guess_suffix_from_file_content(pdf_file)

        assert result == ".pdf"

    def test_guess_suffix_from_file_content_png(self, tmp_path):
        """Should detect PNG files by magic bytes."""
        from copaw.app.channels.dingtalk.utils import (
            guess_suffix_from_file_content,
        )

        png_file = tmp_path / "test.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n test content")

        result = guess_suffix_from_file_content(png_file)

        assert result == ".png"

    def test_guess_suffix_from_file_content_jpg(self, tmp_path):
        """Should detect JPG files by magic bytes."""
        from copaw.app.channels.dingtalk.utils import (
            guess_suffix_from_file_content,
        )

        jpg_file = tmp_path / "test.jpg"
        jpg_file.write_bytes(b"\xff\xd8\xff test content")

        result = guess_suffix_from_file_content(jpg_file)

        assert result == ".jpg"

    def test_guess_suffix_from_file_content_unknown(self, tmp_path):
        """Should return None for unknown file types."""
        from copaw.app.channels.dingtalk.utils import (
            guess_suffix_from_file_content,
        )

        unknown_file = tmp_path / "test.unknown"
        unknown_file.write_bytes(
            b"unknown content that doesn't match any magic"
        )

        result = guess_suffix_from_file_content(unknown_file)

        assert result is None

    def test_guess_suffix_from_nonexistent_file(self, tmp_path):
        """Should handle non-existent file."""
        from copaw.app.channels.dingtalk.utils import (
            guess_suffix_from_file_content,
        )

        result = guess_suffix_from_file_content(tmp_path / "nonexistent.bin")

        assert result is None


# =============================================================================
# P2: Media Upload (HTTP Mock)
# =============================================================================


@pytest.mark.asyncio
class TestDingTalkMediaUpload:
    """Tests for media upload functionality."""

    async def test_upload_media_success(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Successfully upload media file."""
        dingtalk_channel._http = mock_http_session

        # First call: get token
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )

        # Second call: upload media
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=200,
            response_json={
                "errcode": 0,
                "media_id": "media_abc123",
            },
        )

        result = await dingtalk_channel._upload_media(
            data=b"file content",
            media_type="image",
            filename="test.jpg",
        )

        assert result == "media_abc123"

    async def test_upload_media_api_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle media upload API error."""
        dingtalk_channel._http = mock_http_session

        # Token call
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )

        # Upload call returns error
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=200,
            response_json={"errcode": 40001, "errmsg": "upload failed"},
        )

        result = await dingtalk_channel._upload_media(
            data=b"file content",
            media_type="image",
            filename="test.jpg",
        )

        assert result is None

    async def test_upload_media_http_error(
        self,
        dingtalk_channel,
        mock_http_session,
    ):
        """Handle media upload HTTP error."""
        dingtalk_channel._http = mock_http_session

        # Token call
        mock_http_session.expect_post(
            url="https://api.dingtalk.com/v1.0/oauth2/accessToken",
            response_status=200,
            response_json={"accessToken": "token_123", "expireIn": 7200},
        )

        # Upload call returns HTTP error
        mock_http_session.expect_post(
            url="https://oapi.dingtalk.com/media/upload",
            response_status=500,
            response_text="Internal Server Error",
        )

        result = await dingtalk_channel._upload_media(
            data=b"file content",
            media_type="image",
            filename="test.jpg",
        )

        assert result is None


# =============================================================================
# P2: AI Card Store
# =============================================================================


class TestDingTalkAICardStore:
    """Tests for AICardPendingStore."""

    def test_load_empty_store(self, tmp_path):
        """Loading from non-existent file returns empty list."""
        from copaw.app.channels.dingtalk.ai_card import AICardPendingStore

        store = AICardPendingStore(tmp_path / "nonexistent.json")
        result = store.load()

        assert result == []

    def test_load_existing_cards(self, tmp_path):
        """Loading from existing file returns cards."""
        from copaw.app.channels.dingtalk.ai_card import AICardPendingStore

        card_file = tmp_path / "cards.json"
        card_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "pending_cards": [
                        {"account_id": "user1", "card_instance_id": "card1"},
                        {"account_id": "user2", "card_instance_id": "card2"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        store = AICardPendingStore(card_file)
        result = store.load()

        assert len(result) == 2
        assert result[0]["account_id"] == "user1"

    def test_save_cards(self, tmp_path):
        """Saving cards writes to file."""
        from copaw.app.channels.dingtalk.ai_card import (
            AICardPendingStore,
            ActiveAICard,
        )

        store = AICardPendingStore(tmp_path / "cards.json")

        cards = {
            "card1": ActiveAICard(
                card_instance_id="card1",
                access_token="token123",
                conversation_id="conv1",
                account_id="user1",
                store_path="/tmp/card1",
                created_at=1234567890,
                last_updated=1234567890,
                state="2",  # INPUTING
            ),
        }

        store.save(cards)

        saved_file = tmp_path / "cards.json"
        assert saved_file.exists()

        data = json.loads(saved_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert len(data["pending_cards"]) == 1
        # access_token should be stripped
        assert "access_token" not in data["pending_cards"][0]

    def test_save_skips_terminal_states(self, tmp_path):
        """Saving should skip cards in terminal states."""
        from copaw.app.channels.dingtalk.ai_card import (
            AICardPendingStore,
            ActiveAICard,
            FINISHED,
            FAILED,
        )

        store = AICardPendingStore(tmp_path / "cards.json")

        cards = {
            "finished_card": ActiveAICard(
                card_instance_id="finished_card",
                access_token="token",
                conversation_id="conv1",
                account_id="user1",
                store_path="/tmp",
                created_at=1234567890,
                last_updated=1234567890,
                state=FINISHED,
            ),
            "failed_card": ActiveAICard(
                card_instance_id="failed_card",
                access_token="token",
                conversation_id="conv2",
                account_id="user2",
                store_path="/tmp",
                created_at=1234567890,
                last_updated=1234567890,
                state=FAILED,
            ),
            "active_card": ActiveAICard(
                card_instance_id="active_card",
                access_token="token",
                conversation_id="conv3",
                account_id="user3",
                store_path="/tmp",
                created_at=1234567890,
                last_updated=1234567890,
                state="2",  # INPUTING
            ),
        }

        store.save(cards)

        data = json.loads(
            (tmp_path / "cards.json").read_text(encoding="utf-8")
        )
        assert len(data["pending_cards"]) == 1
        assert data["pending_cards"][0]["card_instance_id"] == "active_card"


class TestDingTalkAICardHelpers:
    """Tests for AI card helper functions."""

    def test_is_group_conversation_true(self):
        """Should identify group conversation IDs."""
        from copaw.app.channels.dingtalk.ai_card import is_group_conversation

        result = is_group_conversation("cidabc123")

        assert result is True

    def test_is_group_conversation_false(self):
        """Should identify non-group conversation IDs."""
        from copaw.app.channels.dingtalk.ai_card import is_group_conversation

        result = is_group_conversation("singleabc123")

        assert result is False

    def test_thinking_or_tool_to_card_text_truncates(self):
        """Should truncate long text."""
        from copaw.app.channels.dingtalk.ai_card import (
            thinking_or_tool_to_card_text,
        )

        long_text = "A" * 600
        result = thinking_or_tool_to_card_text(long_text, "Title")

        assert "…" in result  # Should have truncation marker
        assert len(result) < 650  # Should be truncated

    def test_thinking_or_tool_to_card_text_formats_lines(self):
        """Should format lines with blockquote."""
        from copaw.app.channels.dingtalk.ai_card import (
            thinking_or_tool_to_card_text,
        )

        text = "Line 1\nLine 2"
        result = thinking_or_tool_to_card_text(text, "Title")

        assert "> Line 1" in result
        assert "> Line 2" in result
        assert "Title" in result


# =============================================================================
# P2: Ack Early (Streaming)
# =============================================================================


class TestDingTalkAckEarly:
    """Tests for _ack_early method."""

    def test_ack_early_sets_future(self, dingtalk_channel):
        """Should set future result for streaming paths."""
        from copaw.app.channels.dingtalk.constants import SENT_VIA_WEBHOOK

        loop = asyncio.new_event_loop()
        future1 = loop.create_future()
        future2 = loop.create_future()

        meta = {
            "_reply_futures_list": [
                (loop, future1),
                (loop, future2),
            ],
        }

        dingtalk_channel._ack_early(meta, SENT_VIA_WEBHOOK)

        loop.run_until_complete(asyncio.sleep(0.01))

        assert future1.done()
        assert future2.done()
        assert future1.result() == SENT_VIA_WEBHOOK
        assert future2.result() == SENT_VIA_WEBHOOK
        loop.close()


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


# =============================================================================
# P1: Workspace Integration Tests (Mock Workspace)
# =============================================================================


# Helper function for async empty generator
async def async_empty_generator():
    """Helper to create async empty generator."""
    return
    yield  # Make it a generator


@pytest.mark.asyncio
class TestDingTalkWorkspaceIntegration:
    """
    Tests requiring mock workspace.

    Covers _consume_with_tracker, _stream_with_tracker, and
    integration with ChatManager and TaskTracker.
    """

    async def _mock_stream_from_queue(*args, **kwargs):
        """Async generator for stream_from_queue mock."""
        if False:  # Never yields, just for async generator type
            yield None

    @pytest.fixture
    def mock_workspace(self):
        """Create a fully mocked workspace."""
        workspace = MagicMock()

        # Mock chat_manager
        chat_manager = AsyncMock()
        mock_chat = MagicMock()
        mock_chat.id = "chat_123"
        chat_manager.get_or_create_chat.return_value = mock_chat
        workspace.chat_manager = chat_manager

        # Mock task_tracker - use simple MagicMock, test complex path in integration tests
        task_tracker = MagicMock()
        workspace.task_tracker = task_tracker

        return workspace

    @pytest.fixture
    def dingtalk_with_workspace(self, dingtalk_channel, mock_workspace):
        """Channel with mock workspace set."""
        dingtalk_channel.set_workspace(mock_workspace)
        return dingtalk_channel

    async def test_stream_with_tracker_yields_sse_events(
        self,
        dingtalk_with_workspace,
    ):
        """_stream_with_tracker should yield SSE formatted events."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Event,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        mock_event = Event(
            object="message",
            status=RunStatus.Completed,
            type="message.completed",
            id="ev-1",
            created_at=1234567890,
            message=Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[TextContent(type=ContentType.TEXT, text="Hello")],
            ),
        )

        async def mock_process(request):
            yield mock_event

        dingtalk_with_workspace._process = mock_process

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Query"),
            ],
        }

        events = []
        async for event in dingtalk_with_workspace._stream_with_tracker(
            payload
        ):
            events.append(event)
            break  # Just check first event

        assert len(events) == 1
        assert "data:" in events[0]


@pytest.mark.asyncio
class TestDingTalkSendContentParts:
    """
    Tests for send_content_parts method.

    DingTalk-specific behavior for sending various content types.
    """

    async def test_send_content_parts_empty_parts_skipped(
        self,
        dingtalk_channel,
    ):
        """Empty parts list should not send anything."""
        with patch.object(
            dingtalk_channel,
            "_reply_sync",
        ) as mock_reply:
            await dingtalk_channel.send_content_parts(
                to_handle="user123",
                parts=[],
                meta={},
            )

            mock_reply.assert_not_called()

    async def test_send_content_parts_with_file(
        self,
        dingtalk_channel,
        mock_http_session,
        tmp_path,
    ):
        """Send with file content uploads file and sends via webhook."""
        dingtalk_channel._http = mock_http_session

        from copaw.app.channels.base import FileContent, ContentType

        # Create a test file
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test content")

        with patch.object(
            dingtalk_channel,
            "_upload_media",
            return_value="media_file_123",
        ) as mock_upload:
            with patch.object(
                dingtalk_channel,
                "_send_payload_via_session_webhook",
                return_value=True,
            ) as mock_send:
                parts = [
                    FileContent(
                        type=ContentType.FILE,
                        file_url=str(test_file),
                    ),
                ]

                await dingtalk_channel.send_content_parts(
                    to_handle="user123",
                    parts=parts,
                    meta={"session_webhook": "http://webhook.url"},
                )

                mock_upload.assert_called_once()


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


@pytest.mark.asyncio
class TestDingTalkEdgeCases:
    """Additional edge case tests."""

    async def test_start_disabled_channel(self, dingtalk_channel):
        """Starting disabled channel should succeed without action."""
        dingtalk_channel.enabled = False

        # Should not raise
        await dingtalk_channel.start()

    async def test_stop_disabled_channel(self, dingtalk_channel):
        """Stopping disabled channel should succeed without action."""
        dingtalk_channel.enabled = False

        # Should not raise
        await dingtalk_channel.stop()

    async def test_stop_without_start(self, dingtalk_channel):
        """Stopping without prior start should succeed."""
        # Should not raise
        await dingtalk_channel.stop()
