# -*- coding: utf-8 -*-
"""
Feishu Channel Unit Tests

Comprehensive unit tests for FeishuChannel covering:
- Initialization and configuration (from_env, from_config)
- Session ID resolution and routing
- Receive ID store management (for proactive send)
- Message deduplication
- Nickname caching
- Utility methods (sync and async)
- Send methods

Test Patterns:
- Uses tmp_path fixture for temporary paths
- Uses AsyncMock for async methods
- @pytest.mark.asyncio only on async test methods

Run:
    pytest tests/unit/channels/test_feishu.py -v
    pytest tests/unit/channels/test_feishu.py::TestFeishuChannelInit -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=broad-exception-raised
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
def feishu_channel(
    mock_process_handler,
    temp_media_dir,
) -> Generator:
    """Create a FeishuChannel instance for testing."""
    from copaw.app.channels.feishu.channel import FeishuChannel

    channel = FeishuChannel(
        process=mock_process_handler,
        enabled=True,
        app_id="test_app_id_123456",
        app_secret="test_app_secret_abcdef",
        bot_prefix="[TestBot] ",
        media_dir=str(temp_media_dir),
        show_tool_details=False,
        filter_tool_messages=True,
    )
    yield channel


@pytest.fixture
def feishu_channel_with_workspace(
    mock_process_handler,
    temp_workspace_dir,
) -> Generator:
    """Create a FeishuChannel with workspace for testing."""
    from copaw.app.channels.feishu.channel import FeishuChannel

    channel = FeishuChannel(
        process=mock_process_handler,
        enabled=True,
        app_id="test_app_id_789",
        app_secret="test_app_secret_xyz",
        bot_prefix="[WorkspaceBot] ",
        workspace_dir=temp_workspace_dir,
        show_tool_details=False,
        filter_tool_messages=True,
    )
    yield channel


@pytest.fixture
def mock_lark_client():
    """Mock lark_oapi client."""
    mock_client = MagicMock()
    mock_client._config = MagicMock()
    return mock_client


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestFeishuChannelInit:
    """
    Tests for FeishuChannel initialization and factory methods.
    Verifies correct storage of configuration parameters.
    """

    def test_init_stores_basic_config(
        self,
        mock_process_handler,
        temp_media_dir,
    ):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="my_app_id",
            app_secret="my_app_secret",
            bot_prefix="[Bot] ",
            encrypt_key="my_encrypt_key",
            verification_token="my_token",
            media_dir=str(temp_media_dir),
        )

        assert channel.enabled is True
        assert channel.app_id == "my_app_id"
        assert channel.app_secret == "my_app_secret"
        assert channel.bot_prefix == "[Bot] "
        assert channel.encrypt_key == "my_encrypt_key"
        assert channel.verification_token == "my_token"
        assert channel.channel == "feishu"

    def test_init_uses_default_domain(self, mock_process_handler):
        """Constructor should default domain to 'feishu'."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
        )

        assert channel.domain == "feishu"

    def test_init_accepts_lark_domain(self, mock_process_handler):
        """Constructor should accept 'lark' as domain."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
            domain="lark",
        )

        assert channel.domain == "lark"

    def test_init_rejects_invalid_domain(self, mock_process_handler):
        """Constructor should fallback to 'feishu' for invalid domain."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
            domain="invalid_domain",
        )

        assert channel.domain == "feishu"

    def test_init_creates_required_data_structures(
        self,
        mock_process_handler,
    ):
        """Constructor should initialize required internal data structures."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
        )

        # Message ID deduplication
        assert hasattr(channel, "_processed_message_ids")
        assert isinstance(channel._processed_message_ids, dict)

        # Receive ID store
        assert hasattr(channel, "_receive_id_store")
        assert isinstance(channel._receive_id_store, dict)

        # Nickname cache
        assert hasattr(channel, "_nickname_cache")
        assert isinstance(channel._nickname_cache, dict)

        # Clock offset
        assert hasattr(channel, "_clock_offset")
        assert channel._clock_offset == 0

    def test_init_creates_locks(self, mock_process_handler):
        """Constructor should create required locks for thread safety."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
        )

        # Receive ID lock
        assert hasattr(channel, "_receive_id_lock")
        lock_type = type(channel._receive_id_lock).__name__
        assert "Lock" in lock_type

        # Nickname cache lock
        assert hasattr(channel, "_nickname_cache_lock")
        lock_type = type(channel._nickname_cache_lock).__name__
        assert "Lock" in lock_type

    def test_channel_type_is_feishu(self, feishu_channel):
        """Channel type must be 'feishu'."""
        assert feishu_channel.channel == "feishu"


class TestFeishuChannelFromEnv:
    """Tests for from_env factory method."""

    def test_from_env_reads_basic_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read basic environment variables."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        monkeypatch.setenv("FEISHU_CHANNEL_ENABLED", "0")
        monkeypatch.setenv("FEISHU_APP_ID", "env_app_id")
        monkeypatch.setenv("FEISHU_APP_SECRET", "env_app_secret")
        monkeypatch.setenv("FEISHU_BOT_PREFIX", "[EnvBot] ")
        monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "env_encrypt_key")
        monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "env_token")

        channel = FeishuChannel.from_env(mock_process_handler)

        assert channel.enabled is False
        assert channel.app_id == "env_app_id"
        assert channel.app_secret == "env_app_secret"
        assert channel.bot_prefix == "[EnvBot] "
        assert channel.encrypt_key == "env_encrypt_key"
        assert channel.verification_token == "env_token"

    def test_from_env_reads_domain(self, mock_process_handler, monkeypatch):
        """from_env should read FEISHU_DOMAIN environment variable."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        monkeypatch.setenv("FEISHU_APP_ID", "test_id")
        monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret")
        monkeypatch.setenv("FEISHU_DOMAIN", "lark")

        channel = FeishuChannel.from_env(mock_process_handler)

        assert channel.domain == "lark"

    def test_from_env_allow_from_parsing(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should parse FEISHU_ALLOW_FROM correctly."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        monkeypatch.setenv("FEISHU_APP_ID", "test_id")
        monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret")
        monkeypatch.setenv("FEISHU_ALLOW_FROM", "user1,user2,user3")

        channel = FeishuChannel.from_env(mock_process_handler)

        assert "user1" in channel.allow_from
        assert "user2" in channel.allow_from
        assert "user3" in channel.allow_from

    def test_from_env_allow_from_empty(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should handle empty FEISHU_ALLOW_FROM."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        monkeypatch.setenv("FEISHU_APP_ID", "test_id")
        monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret")
        monkeypatch.setenv("FEISHU_ALLOW_FROM", "")

        channel = FeishuChannel.from_env(mock_process_handler)

        assert channel.allow_from == set()

    def test_from_env_require_mention(self, mock_process_handler, monkeypatch):
        """from_env should parse FEISHU_REQUIRE_MENTION correctly."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        monkeypatch.setenv("FEISHU_APP_ID", "test_id")
        monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret")
        monkeypatch.setenv("FEISHU_REQUIRE_MENTION", "1")

        channel = FeishuChannel.from_env(mock_process_handler)

        assert channel.require_mention is True

    def test_from_env_defaults(self, mock_process_handler, monkeypatch):
        """from_env should use sensible defaults."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        monkeypatch.setenv("FEISHU_APP_ID", "test_id")
        monkeypatch.setenv("FEISHU_APP_SECRET", "test_secret")
        monkeypatch.delenv("FEISHU_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("FEISHU_BOT_PREFIX", raising=False)
        monkeypatch.delenv("FEISHU_REQUIRE_MENTION", raising=False)
        monkeypatch.delenv("FEISHU_DOMAIN", raising=False)

        channel = FeishuChannel.from_env(mock_process_handler)

        assert channel.enabled is False  # Default disabled
        assert channel.bot_prefix == ""  # Default empty
        assert channel.require_mention is False  # Default False
        assert channel.domain == "feishu"  # Default domain


class TestFeishuChannelFromConfig:
    """Tests for from_config factory method."""

    def test_from_config_uses_config_values(self, mock_process_handler):
        """from_config should use values from config object."""
        from copaw.app.channels.feishu.channel import FeishuChannel
        from copaw.config.config import FeishuConfig

        config = FeishuConfig(
            enabled=False,
            app_id="config_app_id",
            app_secret="config_app_secret",
            bot_prefix="[ConfigBot] ",
            encrypt_key="config_key",
            verification_token="config_token",
            dm_policy="allowlist",
            group_policy="allowlist",
            require_mention=True,
            domain="lark",
        )

        channel = FeishuChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is False
        assert channel.app_id == "config_app_id"
        assert channel.app_secret == "config_app_secret"
        assert channel.bot_prefix == "[ConfigBot] "
        assert channel.encrypt_key == "config_key"
        assert channel.verification_token == "config_token"
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"
        assert channel.require_mention is True
        assert channel.domain == "lark"

    def test_from_config_with_workspace(self, mock_process_handler, tmp_path):
        """from_config should use workspace_dir when provided."""
        from copaw.app.channels.feishu.channel import FeishuChannel
        from copaw.config.config import FeishuConfig

        config = FeishuConfig(
            enabled=True,
            app_id="test_id",
            app_secret="test_secret",
        )

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        channel = FeishuChannel.from_config(
            process=mock_process_handler,
            config=config,
            workspace_dir=workspace_dir,
        )

        assert channel._workspace_dir == workspace_dir


# =============================================================================
# P0: Session ID Resolution
# =============================================================================


class TestFeishuChannelResolveSessionId:
    """Tests for session ID resolution."""

    def test_resolve_session_id_with_group_chat(self, feishu_channel):
        """Should use chat_id for group chat session ID."""
        meta = {
            "feishu_chat_id": "oc_1234567890abcdef",
            "feishu_chat_type": "group",
        }

        session_id = feishu_channel.resolve_session_id("sender_123", meta)

        # Should be: last4(app_id) + _ + last8(chat_id)
        assert "3456" in session_id  # last 4 of "test_app_id_123456"
        assert "0abcdef" in session_id  # last 8 of chat_id

    def test_resolve_session_id_with_p2p_chat(self, feishu_channel):
        """Should use sender_id for p2p chat session ID."""
        meta = {
            "feishu_chat_id": "",
            "feishu_chat_type": "p2p",
        }

        session_id = feishu_channel.resolve_session_id(
            "ou_abcdef1234567890",
            meta,
        )

        assert "567890" in session_id  # last 8 of sender_id

    def test_resolve_session_id_fallback_to_chat_id(self, feishu_channel):
        """Should fallback to chat_id when no sender_id."""
        meta = {
            "feishu_chat_id": "oc_fallback12345",
            "feishu_chat_type": "p2p",
        }

        session_id = feishu_channel.resolve_session_id("", meta)

        assert "back1234" in session_id  # last 8 of chat_id

    def test_resolve_session_id_no_chat_no_sender(self, feishu_channel):
        """Should use channel prefix when no chat_id or sender_id."""
        meta = {
            "feishu_chat_id": "",
            "feishu_chat_type": "p2p",
        }

        session_id = feishu_channel.resolve_session_id("", meta)

        assert session_id.startswith("feishu:")


# =============================================================================
# P1: Receive ID Store Management (Critical for proactive send)
# =============================================================================


class TestFeishuChannelReceiveIdStore:
    """
    Tests for receive_id store storage and retrieval.

    The receive_id store is used for proactive send (cron jobs).
    It persists to disk so send can work after restart.
    """

    @pytest.mark.asyncio
    async def test_save_receive_id_stores_in_memory(self, feishu_channel):
        """Saving receive_id should store it in memory."""
        await feishu_channel._save_receive_id(
            session_id="test_session_123",
            receive_id="ou_receiver456",
            receive_id_type="open_id",
        )

        assert "test_session_123" in feishu_channel._receive_id_store
        stored = feishu_channel._receive_id_store["test_session_123"]
        assert stored == ("open_id", "ou_receiver456")

    @pytest.mark.asyncio
    async def test_save_receive_id_persists_to_disk(
        self,
        feishu_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Saving receive_id should persist to disk for recovery."""
        channel = feishu_channel_with_workspace

        await channel._save_receive_id(
            session_id="disk_test_session",
            receive_id="ou_disk_user",
            receive_id_type="open_id",
        )

        # Check file exists
        store_path = temp_workspace_dir / "feishu_receive_ids.json"
        assert store_path.exists()

        # Verify content
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "disk_test_session" in data
        assert data["disk_test_session"] == ["open_id", "ou_disk_user"]

    @pytest.mark.asyncio
    async def test_load_receive_id_from_memory(self, feishu_channel):
        """Loading receive_id should first check memory."""
        # Pre-populate memory store
        feishu_channel._receive_id_store["mem_test"] = (
            "chat_id",
            "oc_mem_chat",
        )

        result = await feishu_channel._load_receive_id("mem_test")

        assert result == ("chat_id", "oc_mem_chat")

    @pytest.mark.asyncio
    async def test_load_receive_id_from_disk(
        self,
        feishu_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Loading receive_id should fallback to disk if not in memory."""
        channel = feishu_channel_with_workspace

        # Create file manually
        store_path = temp_workspace_dir / "feishu_receive_ids.json"
        data = {
            "disk_test": ["open_id", "ou_from_disk"],
        }
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = await channel._load_receive_id("disk_test")

        assert result == ("open_id", "ou_from_disk")

    @pytest.mark.asyncio
    async def test_load_receive_id_not_found_returns_none(
        self,
        feishu_channel,
    ):
        """Loading non-existent receive_id should return None."""
        result = await feishu_channel._load_receive_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_load_receive_id_empty_session_returns_none(
        self,
        feishu_channel,
    ):
        """Loading with empty session_id should return None."""
        result = await feishu_channel._load_receive_id("")

        assert result is None

    @pytest.mark.asyncio
    async def test_save_receive_id_empty_session_skips(self, feishu_channel):
        """Saving with empty session_id should be skipped."""
        await feishu_channel._save_receive_id(
            session_id="",
            receive_id="ou_test",
            receive_id_type="open_id",
        )

        assert "" not in feishu_channel._receive_id_store

    @pytest.mark.asyncio
    async def test_save_receive_id_empty_receive_id_skips(
        self,
        feishu_channel,
    ):
        """Saving with empty receive_id should be skipped."""
        await feishu_channel._save_receive_id(
            session_id="test_session",
            receive_id="",
            receive_id_type="open_id",
        )

        assert "test_session" not in feishu_channel._receive_id_store

    @pytest.mark.asyncio
    async def test_save_receive_id_also_keys_by_open_id(self, feishu_channel):
        """Saving should also key by open_id for direct lookup."""
        await feishu_channel._save_receive_id(
            session_id="session_abc",
            receive_id="ou_direct_user",
            receive_id_type="open_id",
        )

        # Should be accessible by open_id too
        result = await feishu_channel._load_receive_id("ou_direct_user")
        assert result == ("open_id", "ou_direct_user")


# =============================================================================
# P1: Route from Handle
# =============================================================================


class TestFeishuChannelRouteFromHandle:
    """Tests for _route_from_handle method."""

    def test_route_from_handle_session_key(self, feishu_channel):
        """Should parse feishu:sw: prefix as session_key."""
        result = feishu_channel._route_from_handle("feishu:sw:abc123")

        assert result["session_key"] == "abc123"

    def test_route_from_handle_chat_id(self, feishu_channel):
        """Should parse feishu:chat_id: prefix."""
        result = feishu_channel._route_from_handle("feishu:chat_id:oc_test123")

        assert result["receive_id_type"] == "chat_id"
        assert result["receive_id"] == "oc_test123"

    def test_route_from_handle_open_id(self, feishu_channel):
        """Should parse feishu:open_id: prefix."""
        result = feishu_channel._route_from_handle(
            "feishu:open_id:ou_user456",
        )

        assert result["receive_id_type"] == "open_id"
        assert result["receive_id"] == "ou_user456"

    def test_route_from_handle_direct_chat_id(self, feishu_channel):
        """Should recognize raw chat_id starting with oc_."""
        result = feishu_channel._route_from_handle("oc_direct_chat")

        assert result["receive_id_type"] == "chat_id"
        assert result["receive_id"] == "oc_direct_chat"

    def test_route_from_handle_direct_open_id(self, feishu_channel):
        """Should recognize raw open_id starting with ou_."""
        result = feishu_channel._route_from_handle("ou_direct_user")

        assert result["receive_id_type"] == "open_id"
        assert result["receive_id"] == "ou_direct_user"

    def test_route_from_handle_fallback(self, feishu_channel):
        """Should default to open_id for unknown formats."""
        result = feishu_channel._route_from_handle("random_id")

        assert result["receive_id_type"] == "open_id"
        assert result["receive_id"] == "random_id"


# =============================================================================
# P1: To Handle from Target
# =============================================================================


class TestFeishuChannelToHandleFromTarget:
    """Tests for to_handle_from_target method."""

    def test_to_handle_from_target_with_session(self, feishu_channel):
        """Should create handle with session_id."""
        result = feishu_channel.to_handle_from_target(
            user_id="ou_user123",
            session_id="session_abc",
        )

        assert result == "feishu:sw:session_abc"

    def test_to_handle_from_target_without_session(self, feishu_channel):
        """Should fallback to user_id when no session."""
        result = feishu_channel.to_handle_from_target(
            user_id="ou_user456",
            session_id="",
        )

        assert result == "feishu:open_id:ou_user456"

    def test_to_handle_from_target_empty_user_and_session(
        self,
        feishu_channel,
    ):
        """Should return empty string when both are empty."""
        result = feishu_channel.to_handle_from_target(
            user_id="",
            session_id="",
        )

        assert result == "feishu:open_id:"


# =============================================================================
# P0: Message Deduplication
# =============================================================================


class TestFeishuChannelMessageDeduplication:
    """
    Tests for message deduplication.

    Feishu may retry message delivery; we need to dedup by message_id.
    """

    def test_message_id_tracked(self, feishu_channel):
        """Processed message IDs should be tracked."""
        from copaw.app.channels.feishu.constants import (
            FEISHU_PROCESSED_IDS_MAX,
        )

        # Initially empty
        assert len(feishu_channel._processed_message_ids) == 0

        # Add a message ID
        feishu_channel._processed_message_ids["msg_123"] = None

        assert "msg_123" in feishu_channel._processed_message_ids

    def test_message_id_trims_when_over_limit(self, feishu_channel):
        """Old message IDs should be trimmed when over limit."""
        from copaw.app.channels.feishu.constants import (
            FEISHU_PROCESSED_IDS_MAX,
        )

        max_size = FEISHU_PROCESSED_IDS_MAX

        # Add more IDs than the limit
        for i in range(max_size + 10):
            feishu_channel._processed_message_ids[f"msg_{i}"] = None
            # Simulate the trimming behavior
            while len(feishu_channel._processed_message_ids) > max_size:
                feishu_channel._processed_message_ids.popitem(last=False)

        # Should be at most max_size
        assert len(feishu_channel._processed_message_ids) <= max_size


# =============================================================================
# P2: Utility Functions - Synchronous
# =============================================================================


class TestFeishuChannelSyncUtilities:
    """Tests for synchronous utility methods."""

    def test_build_post_content_text_only(self, feishu_channel):
        """Should build post content with text only."""
        result = feishu_channel._build_post_content("Hello World", [])

        assert "zh_cn" in result
        assert "content" in result["zh_cn"]
        assert result["zh_cn"]["content"][0][0]["tag"] == "md"
        assert result["zh_cn"]["content"][0][0]["text"] == "Hello World"

    def test_build_post_content_with_images(self, feishu_channel):
        """Should build post content with images."""
        result = feishu_channel._build_post_content(
            "See this:",
            ["img_key_1", "img_key_2"],
        )

        content = result["zh_cn"]["content"]
        assert len(content) == 3  # text + 2 images
        assert content[0][0]["tag"] == "md"
        assert content[1][0]["tag"] == "img"
        assert content[1][0]["image_key"] == "img_key_1"
        assert content[2][0]["tag"] == "img"

    def test_build_post_content_empty(self, feishu_channel):
        """Should handle empty content gracefully."""
        result = feishu_channel._build_post_content("", [])

        # Should have a placeholder
        assert result["zh_cn"]["content"][0][0]["text"] == "[empty]"

    def test_receive_id_store_path_with_workspace(
        self,
        feishu_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Should use workspace directory when available."""
        path = feishu_channel_with_workspace._receive_id_store_path()

        assert path == temp_workspace_dir / "feishu_receive_ids.json"

    def test_get_on_reply_sent_args(self, feishu_channel):
        """Should return user_id and session_id."""
        mock_request = MagicMock()
        mock_request.user_id = "user_123"
        mock_request.session_id = "session_456"

        result = feishu_channel.get_on_reply_sent_args(
            mock_request,
            "to_handle",
        )

        assert result == ("user_123", "session_456")


# =============================================================================
# P0: Enabled Check
# =============================================================================


class TestFeishuChannelEnabledCheck:
    """Tests for enabled/disabled behavior."""

    @pytest.mark.asyncio
    async def test_send_content_parts_returns_none_when_disabled(
        self,
        mock_process_handler,
        temp_media_dir,
    ):
        """send_content_parts should return None when channel disabled."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=False,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
            media_dir=str(temp_media_dir),
        )

        result = await channel.send_content_parts(
            to_handle="feishu:sw:test",
            parts=[],
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_send_returns_none_when_disabled(
        self,
        mock_process_handler,
        temp_media_dir,
    ):
        """send should return None when channel disabled."""
        from copaw.app.channels.feishu.channel import FeishuChannel

        channel = FeishuChannel(
            process=mock_process_handler,
            enabled=False,
            app_id="test_id",
            app_secret="test_secret",
            bot_prefix="",
            media_dir=str(temp_media_dir),
        )

        # Should not raise and should return silently
        await channel.send(
            to_handle="feishu:sw:test",
            text="Hello",
        )

        # If we get here without error, the test passed
        assert True


# =============================================================================
# P1: Build Agent Request
# =============================================================================


class TestFeishuChannelBuildAgentRequest:
    """Tests for build_agent_request_from_native method."""

    def test_build_agent_request_from_native_basic(self, feishu_channel):
        """Should build AgentRequest from native payload."""
        payload = {
            "channel_id": "feishu",
            "sender_id": "sender#1234",
            "user_id": "user#5678",
            "session_id": "session_abc",
            "content_parts": [{"type": "text", "text": "Hello"}],
            "meta": {"feishu_chat_id": "oc_test"},
        }

        result = feishu_channel.build_agent_request_from_native(payload)

        assert result.channel_id == "feishu"
        assert hasattr(result, "channel_meta")
        assert result.channel_meta.get("feishu_chat_id") == "oc_test"

    def test_build_agent_request_uses_payload_session_id(self, feishu_channel):
        """Should use session_id from payload when available."""
        payload = {
            "channel_id": "feishu",
            "sender_id": "sender#1234",
            "session_id": "explicit_session",
            "content_parts": [],
            "meta": {},
        }

        result = feishu_channel.build_agent_request_from_native(payload)

        assert result.session_id == "explicit_session"

    def test_build_agent_request_extracts_sender_from_meta(
        self,
        feishu_channel,
    ):
        """Should prefer feishu_sender_id from meta for user_id."""
        payload = {
            "channel_id": "feishu",
            "sender_id": "display#1234",
            "user_id": "fallback#5678",
            "session_id": "session_abc",
            "content_parts": [],
            "meta": {"feishu_sender_id": "ou_real_sender"},
        }

        result = feishu_channel.build_agent_request_from_native(payload)

        assert result.user_id == "ou_real_sender"


# =============================================================================
# P1: Merge Native Items
# =============================================================================


class TestFeishuChannelMergeNativeItems:
    """Tests for merge_native_items method."""

    def test_merge_native_items_concat_content_parts(self, feishu_channel):
        """Should concatenate content_parts from multiple items."""
        items = [
            {
                "channel_id": "feishu",
                "sender_id": "user1",
                "content_parts": [{"type": "text", "text": "Hello "}],
                "meta": {"seq": 1},
            },
            {
                "channel_id": "feishu",
                "sender_id": "user1",
                "content_parts": [{"type": "text", "text": "World"}],
                "meta": {"seq": 2},
            },
        ]

        result = feishu_channel.merge_native_items(items)

        assert len(result["content_parts"]) == 2
        assert result["content_parts"][0]["text"] == "Hello "
        assert result["content_parts"][1]["text"] == "World"

    def test_merge_native_items_empty_list(self, feishu_channel):
        """Should return None for empty list."""
        result = feishu_channel.merge_native_items([])

        assert result is None

    def test_merge_native_items_single_item(self, feishu_channel):
        """Should return merged item for single item."""
        items = [
            {
                "channel_id": "feishu",
                "sender_id": "user1",
                "content_parts": [{"type": "image", "url": "img.jpg"}],
                "meta": {"id": "msg_1"},
            },
        ]

        result = feishu_channel.merge_native_items(items)

        assert len(result["content_parts"]) == 1
        assert result["sender_id"] == "user1"

    def test_merge_native_items_uses_last_sender(self, feishu_channel):
        """Should use sender_id from last item."""
        items = [
            {
                "channel_id": "feishu",
                "sender_id": "old_sender",
                "content_parts": [],
                "meta": {},
            },
            {
                "channel_id": "feishu",
                "sender_id": "new_sender",
                "content_parts": [],
                "meta": {},
            },
        ]

        result = feishu_channel.merge_native_items(items)

        assert result["sender_id"] == "new_sender"


# =============================================================================
# P1: Get Receive for Send
# =============================================================================


class TestFeishuChannelGetReceiveForSend:
    """Tests for _get_receive_for_send method."""

    @pytest.mark.asyncio
    async def test_get_receive_from_meta(self, feishu_channel):
        """Should prefer receive_id from meta."""
        meta = {
            "feishu_receive_id": "ou_from_meta",
            "feishu_receive_id_type": "open_id",
        }

        result = await feishu_channel._get_receive_for_send(
            "feishu:sw:any",
            meta,
        )

        assert result == ("open_id", "ou_from_meta")

    @pytest.mark.asyncio
    async def test_get_receive_from_store(self, feishu_channel):
        """Should load from store when session_key provided."""
        # Pre-populate store
        feishu_channel._receive_id_store["my_session"] = (
            "chat_id",
            "oc_stored_chat",
        )

        result = await feishu_channel._get_receive_for_send(
            "feishu:sw:my_session",
            {},
        )

        assert result == ("chat_id", "oc_stored_chat")

    @pytest.mark.asyncio
    async def test_get_receive_from_direct_chat_id(self, feishu_channel):
        """Should handle direct chat_id."""
        result = await feishu_channel._get_receive_for_send(
            "feishu:chat_id:oc_direct123",
            {},
        )

        assert result == ("chat_id", "oc_direct123")

    @pytest.mark.asyncio
    async def test_get_receive_returns_none_when_not_found(
        self,
        feishu_channel,
    ):
        """Should return None when receive_id cannot be resolved."""
        result = await feishu_channel._get_receive_for_send(
            "feishu:sw:unknown_session",
            {},
        )

        assert result is None


# =============================================================================
# P2: File Upload Size Check
# =============================================================================


class TestFeishuChannelFileUpload:
    """Tests for file upload size checking."""

    @pytest.mark.asyncio
    async def test_upload_file_rejects_too_large(
        self,
        feishu_channel,
        tmp_path,
    ):
        """Should return None for files exceeding max size."""
        from copaw.app.channels.feishu.constants import FEISHU_FILE_MAX_BYTES

        # Create a file just over the limit
        large_file = tmp_path / "large.bin"
        large_file.write_bytes(b"x" * (FEISHU_FILE_MAX_BYTES + 1))

        # Mock client to avoid SDK calls
        feishu_channel._client = MagicMock()

        result = await feishu_channel._upload_file(str(large_file))

        assert result is None


# =============================================================================
# P1: Part to Image Bytes
# =============================================================================


class TestFeishuChannelPartToImageBytes:
    """Tests for _part_to_image_bytes method."""

    @pytest.mark.asyncio
    async def test_part_to_image_bytes_from_base64(self, feishu_channel):
        """Should decode base64 image data."""
        import base64

        part = MagicMock()
        part.image_url = "data:image/png;base64,aGVsbG8="
        part.filename = "test.png"

        data, filename = await feishu_channel._part_to_image_bytes(part)

        assert data == b"hello"
        assert filename == "test.png"

    @pytest.mark.asyncio
    async def test_part_to_image_bytes_invalid_base64(self, feishu_channel):
        """Should handle invalid base64 gracefully."""
        part = MagicMock()
        part.image_url = "data:image/png;base64,!!!invalid!!!"
        part.filename = "test.png"

        data, filename = await feishu_channel._part_to_image_bytes(part)

        assert data is None
        assert filename == "test.png"

    @pytest.mark.asyncio
    async def test_part_to_image_bytes_no_url(self, feishu_channel):
        """Should return (None, filename) when no image_url."""
        part = MagicMock()
        part.image_url = None
        part.filename = "none.png"

        data, filename = await feishu_channel._part_to_image_bytes(part)

        assert data is None
        assert filename == "none.png"


# =============================================================================
# P2: Part to File Path or URL
# =============================================================================


class TestFeishuChannelPartToFilePathOrUrl:
    """Tests for _part_to_file_path_or_url method."""

    @pytest.mark.asyncio
    async def test_part_to_file_path_from_base64(
        self,
        feishu_channel,
        tmp_path,
    ):
        """Should save base64 data to temp file and return path."""
        import base64

        # Use actual media dir
        feishu_channel._media_dir = tmp_path / "media"
        feishu_channel._media_dir.mkdir(parents=True, exist_ok=True)

        test_data = b"test file content"
        b64_data = base64.b64encode(test_data).decode()

        part = MagicMock()
        part.file_url = f"data:application/octet-stream;base64,{b64_data}"
        part.filename = "test.txt"

        result = await feishu_channel._part_to_file_path_or_url(part)

        assert result is not None
        assert Path(result).exists()
        assert Path(result).read_bytes() == test_data

    @pytest.mark.asyncio
    async def test_part_to_file_path_invalid_base64(self, feishu_channel):
        """Should return None for invalid base64."""
        part = MagicMock()
        part.file_url = "data:application/octet-stream;base64,!!!invalid!!!"
        part.filename = "test.txt"

        result = await feishu_channel._part_to_file_path_or_url(part)

        assert result is None

    def test_part_to_file_path_with_local_path(self, feishu_channel, tmp_path):
        """Should return path for existing local file."""
        test_file = tmp_path / "local.txt"
        test_file.write_text("local content")

        part = MagicMock()
        part.file_url = str(test_file)
        part.filename = "local.txt"

        result = asyncio.run(
            feishu_channel._part_to_file_path_or_url(part),
        )

        assert result == str(test_file)

    def test_part_to_file_path_with_http_url(self, feishu_channel):
        """Should return HTTP URL directly."""
        part = MagicMock()
        part.file_url = "https://example.com/file.pdf"
        part.filename = "file.pdf"

        result = asyncio.run(
            feishu_channel._part_to_file_path_or_url(part),
        )

        assert result == "https://example.com/file.pdf"

    @pytest.mark.asyncio
    async def test_part_to_file_path_with_file_url(
        self,
        feishu_channel,
        tmp_path,
    ):
        """Should handle file:// URLs."""
        test_file = tmp_path / "file_url_test.txt"
        test_file.write_text("content via file url")

        part = MagicMock()
        part.file_url = f"file://{test_file}"
        part.filename = "file_url_test.txt"

        result = await feishu_channel._part_to_file_path_or_url(part)

        assert result == str(test_file)


# =============================================================================
# P2: Load/Store File Backward Compatibility
# =============================================================================


class TestFeishuChannelReceiveIdStoreBackwardCompat:
    """Tests for backward compatibility in receive_id store."""

    @pytest.mark.asyncio
    async def test_load_receive_id_store_backward_compat(
        self,
        feishu_channel_with_workspace,
        temp_workspace_dir,
    ):
        """Should handle old format [receive_id, receive_id_type]."""
        channel = feishu_channel_with_workspace

        # Create file with old format (reversed order)
        store_path = temp_workspace_dir / "feishu_receive_ids.json"
        old_data = {
            "old_session": ["ou_old_user", "open_id"],  # [id, type] old format
        }
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(old_data, f)

        # Load should normalize to (type, id) format
        channel._load_receive_id_store_from_disk()

        assert "old_session" in channel._receive_id_store
        # Should be stored as (type, id)
        assert channel._receive_id_store["old_session"] == (
            "open_id",
            "ou_old_user",
        )


# =============================================================================
# P2: Fetch Bytes from URL
# =============================================================================


class TestFeishuChannelFetchBytesFromUrl:
    """Tests for _fetch_bytes_from_url method."""

    @pytest.mark.asyncio
    async def test_fetch_bytes_no_http_client(self, feishu_channel):
        """Should return None when http_client not initialized."""
        feishu_channel._http_client = None

        result = await feishu_channel._fetch_bytes_from_url(
            "https://example.com/file.txt",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_bytes_from_local_file(self, feishu_channel, tmp_path):
        """Should read local file directly."""
        # Use actual media dir
        feishu_channel._media_dir = tmp_path / "media"
        feishu_channel._media_dir.mkdir(parents=True, exist_ok=True)

        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")

        # Mock http_client to verify it's not used
        feishu_channel._http_client = MagicMock()

        result = await feishu_channel._fetch_bytes_from_url(
            f"file://{test_file}",
        )

        assert result == b"file content"
        feishu_channel._http_client.get.assert_not_called()


# =============================================================================
# P0: Get On Reply Sent Args
# =============================================================================


class TestFeishuChannelGetOnReplySentArgs:
    """Tests for get_on_reply_sent_args method."""

    def test_returns_user_id_and_session_id(self, feishu_channel):
        """Should return tuple of (user_id, session_id)."""
        mock_request = MagicMock()
        mock_request.user_id = "u123"
        mock_request.session_id = "s456"

        result = feishu_channel.get_on_reply_sent_args(mock_request, "handle")

        assert result == ("u123", "s456")

    def test_handles_empty_values(self, feishu_channel):
        """Should handle empty values gracefully."""
        mock_request = MagicMock()
        mock_request.user_id = ""
        mock_request.session_id = ""

        result = feishu_channel.get_on_reply_sent_args(mock_request, "handle")

        assert result == ("", "")


# =============================================================================
# P0: Get To Handle From Request
# =============================================================================


class TestFeishuChannelGetToHandleFromRequest:
    """Tests for get_to_handle_from_request method."""

    def test_returns_session_based_handle(self, feishu_channel):
        """Should return feishu:sw: prefix with session_id."""
        mock_request = MagicMock()
        mock_request.session_id = "abc123"
        mock_request.user_id = "user456"

        result = feishu_channel.get_to_handle_from_request(mock_request)

        assert result == "feishu:sw:abc123"

    def test_fallbacks_to_user_id(self, feishu_channel):
        """Should fallback to feishu:open_id: when no session_id."""
        mock_request = MagicMock()
        mock_request.session_id = ""
        mock_request.user_id = "user789"

        result = feishu_channel.get_to_handle_from_request(mock_request)

        assert result == "feishu:open_id:user789"

    def test_returns_empty_when_both_empty(self, feishu_channel):
        """Should return empty string when both are empty."""
        mock_request = MagicMock()
        mock_request.session_id = ""
        mock_request.user_id = ""

        result = feishu_channel.get_to_handle_from_request(mock_request)

        assert result == ""
