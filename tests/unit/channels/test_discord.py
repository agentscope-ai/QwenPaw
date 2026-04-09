# -*- coding: utf-8 -*-
"""
Discord Channel Unit Tests

Generated using python-test-pattern skill v0.3.0
Tests cover: initialization, factory methods, message chunking,
session resolution, target routing, async send operations,
and lifecycle management.

Run:
    pytest tests/unit/channels/test_discord.py -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process():
    """Create mock process handler."""

    async def mock_handler(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    return AsyncMock(side_effect=mock_handler)


@pytest.fixture
def mock_discord_client():
    """Create mock Discord client."""
    client = MagicMock()
    client.user = MagicMock()
    client.user.id = 123456789
    client.is_ready = Mock(return_value=True)
    client.get_channel = Mock(return_value=None)
    client.fetch_channel = AsyncMock()
    client.get_user = Mock(return_value=None)
    client.fetch_user = AsyncMock()
    client.close = AsyncMock()
    client.start = AsyncMock()
    return client


@pytest.fixture
def discord_channel_disabled(mock_process):
    """Create disabled DiscordChannel instance for testing."""
    from copaw.app.channels.discord_.channel import DiscordChannel

    channel = DiscordChannel(
        process=mock_process,
        enabled=False,
        token="",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="",
    )
    return channel


@pytest.fixture
def discord_channel(mock_process):
    """Create DiscordChannel instance for testing
    (disabled to avoid client init).
    """
    from copaw.app.channels.discord_.channel import DiscordChannel

    channel = DiscordChannel(
        process=mock_process,
        # Disabled to avoid actual Discord client initialization
        enabled=False,
        token="test_token",
        http_proxy="",
        http_proxy_auth="",
        bot_prefix="[BOT] ",
        dm_policy="open",
        group_policy="open",
        allow_from=[],
        deny_message="",
        require_mention=False,
        accept_bot_messages=False,
    )
    return channel


# =============================================================================
# P0: Initialization Tests
# =============================================================================


class TestDiscordChannelInit:
    """
    P0: DiscordChannel initialization tests.
    """

    def test_init_stores_basic_config(self, mock_process):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        channel = DiscordChannel(
            process=mock_process,
            enabled=True,
            token="discord_token_123",
            http_proxy="http://proxy.example.com:8080",
            http_proxy_auth="user:pass",
            bot_prefix="[DiscordBot] ",
        )

        assert channel.enabled is True
        assert channel.token == "discord_token_123"
        assert channel.http_proxy == "http://proxy.example.com:8080"
        assert channel.http_proxy_auth == "user:pass"
        assert channel.bot_prefix == "[DiscordBot] "

    def test_init_stores_policy_config(self, mock_process):
        """Constructor should store policy configuration parameters."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        channel = DiscordChannel(
            process=mock_process,
            enabled=False,
            token="",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="",
            dm_policy="closed",
            group_policy="allowlist",
            allow_from=["user1", "user2"],
            deny_message="Access denied",
            require_mention=True,
            accept_bot_messages=True,
        )

        assert channel.dm_policy == "closed"
        assert channel.group_policy == "allowlist"
        assert channel.allow_from == {"user1", "user2"}
        assert channel.deny_message == "Access denied"
        assert channel.require_mention is True
        assert channel.accept_bot_messages is True

    def test_init_creates_required_data_structures(self, mock_process):
        """Constructor should initialize required internal data structures."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        channel = DiscordChannel(
            process=mock_process,
            enabled=False,
            token="",
            http_proxy="",
            http_proxy_auth="",
            bot_prefix="",
        )

        assert hasattr(channel, "_processed_message_ids")
        assert isinstance(channel._processed_message_ids, set)
        assert hasattr(channel, "_processed_message_id_queue")
        assert hasattr(channel, "_task")
        assert channel._task is None
        assert hasattr(channel, "_client")
        assert channel._client is None

    def test_channel_type_is_discord(self, discord_channel):
        """Channel type must be 'discord'."""
        assert discord_channel.channel == "discord"

    def test_uses_manager_queue_is_true(self, discord_channel):
        """Discord channel uses manager queue."""
        assert discord_channel.uses_manager_queue is True

    def test_max_cached_message_ids_constant(self, discord_channel):
        """Max cached message IDs should be 500."""
        assert discord_channel._MAX_CACHED_MESSAGE_IDS == 500

    def test_discord_max_len_constant(self, discord_channel):
        """Discord max message length should be 2000."""
        assert discord_channel._DISCORD_MAX_LEN == 2000


# =============================================================================
# P0: Factory Method Tests
# =============================================================================


class TestDiscordChannelFromEnv:
    """
    P0: Tests for from_env factory method.
    """

    def test_from_env_reads_basic_env_vars(self, mock_process, monkeypatch):
        """from_env should read basic environment variables."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        monkeypatch.setenv("DISCORD_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env_token_123")
        monkeypatch.setenv("DISCORD_HTTP_PROXY", "http://env.proxy:8080")
        monkeypatch.setenv("DISCORD_HTTP_PROXY_AUTH", "env_user:env_pass")
        monkeypatch.setenv("DISCORD_BOT_PREFIX", "[EnvBot] ")

        channel = DiscordChannel.from_env(mock_process)

        assert channel.enabled is True
        assert channel.token == "env_token_123"
        assert channel.http_proxy == "http://env.proxy:8080"
        assert channel.http_proxy_auth == "env_user:env_pass"
        assert channel.bot_prefix == "[EnvBot] "

    def test_from_env_reads_policy_env_vars(self, mock_process, monkeypatch):
        """from_env should read policy environment variables."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        monkeypatch.setenv("DISCORD_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.setenv("DISCORD_DM_POLICY", "closed")
        monkeypatch.setenv("DISCORD_GROUP_POLICY", "allowlist")
        monkeypatch.setenv("DISCORD_ALLOW_FROM", "user1, user2, user3")
        monkeypatch.setenv("DISCORD_DENY_MESSAGE", "Custom deny message")
        monkeypatch.setenv("DISCORD_REQUIRE_MENTION", "1")
        monkeypatch.setenv("DISCORD_ACCEPT_BOT_MESSAGES", "1")

        channel = DiscordChannel.from_env(mock_process)

        assert channel.dm_policy == "closed"
        assert channel.group_policy == "allowlist"
        assert channel.allow_from == {"user1", "user2", "user3"}
        assert channel.deny_message == "Custom deny message"
        assert channel.require_mention is True
        assert channel.accept_bot_messages is True

    def test_from_env_uses_defaults(self, mock_process, monkeypatch):
        """from_env should use defaults when environment variables are missing."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.delenv("DISCORD_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("DISCORD_DM_POLICY", raising=False)
        monkeypatch.delenv("DISCORD_GROUP_POLICY", raising=False)
        monkeypatch.delenv("DISCORD_ALLOW_FROM", raising=False)
        monkeypatch.delenv("DISCORD_REQUIRE_MENTION", raising=False)
        monkeypatch.delenv("DISCORD_ACCEPT_BOT_MESSAGES", raising=False)

        channel = DiscordChannel.from_env(mock_process)

        assert channel.enabled is True  # Default is "1" == "1"
        assert channel.dm_policy == "open"
        assert channel.group_policy == "open"
        assert channel.allow_from == []
        assert channel.require_mention is False
        assert channel.accept_bot_messages is False

    def test_from_env_empty_allow_from(self, mock_process, monkeypatch):
        """from_env should handle empty DISCORD_ALLOW_FROM."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.setenv("DISCORD_ALLOW_FROM", "")

        channel = DiscordChannel.from_env(mock_process)

        assert channel.allow_from == []


class TestDiscordChannelFromConfig:
    """
    P0: Tests for from_config factory method.
    """

    def test_from_config_uses_config_object(self, mock_process):
        """from_config should use configuration object's values."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        mock_config = Mock()
        mock_config.enabled = True
        mock_config.bot_token = "config_token_123"
        mock_config.http_proxy = "http://config.proxy:8080"
        mock_config.http_proxy_auth = "config_user:config_pass"
        mock_config.bot_prefix = "[ConfigBot] "
        mock_config.dm_policy = "closed"
        mock_config.group_policy = "allowlist"
        mock_config.allow_from = ["admin1", "admin2"]
        mock_config.deny_message = "Config deny message"
        mock_config.require_mention = True
        mock_config.accept_bot_messages = True

        channel = DiscordChannel.from_config(
            mock_process,
            config=mock_config,
        )

        assert channel.enabled is True
        assert channel.token == "config_token_123"
        assert channel.http_proxy == "http://config.proxy:8080"
        assert channel.http_proxy_auth == "config_user:config_pass"
        assert channel.bot_prefix == "[ConfigBot] "
        assert channel.dm_policy == "closed"
        assert channel.group_policy == "allowlist"
        assert channel.allow_from == {"admin1", "admin2"}
        assert channel.deny_message == "Config deny message"
        assert channel.require_mention is True
        assert channel.accept_bot_messages is True

    def test_from_config_uses_defaults_for_optional(self, mock_process):
        """from_config should use defaults for optional config values."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        mock_config = Mock()
        mock_config.enabled = False
        mock_config.bot_token = None
        mock_config.http_proxy = None
        mock_config.http_proxy_auth = None
        mock_config.bot_prefix = None
        mock_config.dm_policy = None
        mock_config.group_policy = None
        mock_config.allow_from = None
        mock_config.deny_message = None
        mock_config.require_mention = False
        mock_config.accept_bot_messages = False

        channel = DiscordChannel.from_config(
            mock_process,
            config=mock_config,
        )

        assert channel.token == ""
        assert channel.http_proxy == ""
        assert channel.http_proxy_auth == ""
        assert channel.bot_prefix == ""
        assert channel.dm_policy == "open"
        assert channel.group_policy == "open"
        assert channel.allow_from == set()
        assert channel.deny_message == ""


# =============================================================================
# P0: Static Method Tests (_chunk_text)
# =============================================================================


class TestDiscordChannelChunkText:
    """
    P0: Tests for _chunk_text static method.
    """

    def test_chunk_text_short_text_no_split(self):
        """Short text should not be split."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        text = "Hello, World!"
        chunks = DiscordChannel._chunk_text(text, max_len=2000)

        assert len(chunks) == 1
        assert chunks[0] == "Hello, World!"

    def test_chunk_text_empty_string(self):
        """Empty string should return empty list."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        chunks = DiscordChannel._chunk_text("")

        assert chunks == []

    def test_chunk_text_whitespace_only(self):
        """Whitespace-only string should return empty list."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        chunks = DiscordChannel._chunk_text("   \n\t  ")

        assert chunks == []

    def test_chunk_text_split_at_newlines(self):
        """Text should split at newlines when possible."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        lines = [f"Line {i}" for i in range(100)]
        text = "\n".join(lines)

        chunks = DiscordChannel._chunk_text(text, max_len=500)

        # Verify all lines are preserved
        reconstructed = "\n".join(chunks)
        assert reconstructed == text

    def test_chunk_text_with_code_fences(self):
        """Text with code fences should preserve fence structure."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        text = """```python
def hello():
    print("Hello")
    return "World"
```
Some text after"""

        chunks = DiscordChannel._chunk_text(text, max_len=100)

        # Each chunk should have properly closed fences
        for i, chunk in enumerate(chunks):
            if i < len(chunks) - 1:  # Not the last chunk
                assert chunk.rstrip().endswith("```")

    def test_chunk_text_long_single_line(self):
        """Long single line should be hard-split."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        text = "a" * 5000

        chunks = DiscordChannel._chunk_text(text, max_len=2000)

        # Should be split into multiple chunks
        assert len(chunks) >= 2
        # Each chunk should not exceed max_len (accounting for newlines)
        for chunk in chunks:
            assert len(chunk) <= 2000 + 10  # Allow small margin for newlines

    def test_chunk_text_preserves_formatting(self):
        """Text formatting should be preserved in chunks."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        text = """First paragraph with some content.

Second paragraph with more content.

Third paragraph here."""

        chunks = DiscordChannel._chunk_text(text, max_len=1000)

        # Should preserve paragraph structure
        full_text = "\n".join(chunks)
        assert "First paragraph" in full_text
        assert "Second paragraph" in full_text
        assert "Third paragraph" in full_text


# =============================================================================
# P0: Session ID Resolution Tests
# =============================================================================


class TestDiscordChannelResolveSessionId:
    """
    P0: Tests for resolve_session_id method.
    """

    def test_resolve_session_id_for_dm(self, discord_channel):
        """Should resolve DM session ID correctly."""
        meta = {"is_dm": True, "user_id": "12345"}

        session_id = discord_channel.resolve_session_id("12345", meta)

        assert session_id == "discord:dm:12345"

    def test_resolve_session_id_for_channel(self, discord_channel):
        """Should resolve channel session ID correctly."""
        meta = {"is_dm": False, "channel_id": "67890"}

        session_id = discord_channel.resolve_session_id("12345", meta)

        assert session_id == "discord:ch:67890"

    def test_resolve_session_id_fallback_to_user(self, discord_channel):
        """Should fallback to user ID when channel_id not provided."""
        meta = {"is_dm": False}

        session_id = discord_channel.resolve_session_id("99999", meta)

        assert session_id == "discord:dm:99999"

    def test_resolve_session_id_empty_meta(self, discord_channel):
        """Should handle empty meta."""
        session_id = discord_channel.resolve_session_id("user123", {})

        assert session_id == "discord:dm:user123"

    def test_resolve_session_id_none_meta(self, discord_channel):
        """Should handle None meta."""
        session_id = discord_channel.resolve_session_id("user123", None)

        assert session_id == "discord:dm:user123"


# =============================================================================
# P0: Target Routing Tests
# =============================================================================


class TestDiscordChannelRouteFromHandle:
    """
    P0: Tests for _route_from_handle method.
    """

    def test_route_from_handle_channel(self, discord_channel):
        """Should parse channel handle correctly."""
        route = discord_channel._route_from_handle("discord:ch:123456")

        assert route == {"channel_id": "123456"}

    def test_route_from_handle_dm(self, discord_channel):
        """Should parse DM handle correctly."""
        route = discord_channel._route_from_handle("discord:dm:789012")

        assert route == {"user_id": "789012"}

    def test_route_from_handle_empty(self, discord_channel):
        """Should handle empty handle."""
        route = discord_channel._route_from_handle("")

        assert route == {}

    def test_route_from_handle_invalid_format(self, discord_channel):
        """Should handle invalid format."""
        route = discord_channel._route_from_handle("invalid:format")

        assert route == {}

    def test_route_from_handle_missing_discord_prefix(self, discord_channel):
        """Should require 'discord' prefix."""
        route = discord_channel._route_from_handle("ch:123456")

        assert route == {}


class TestDiscordChannelGetToHandleFromRequest:
    """
    P0: Tests for get_to_handle_from_request method.
    """

    def test_get_to_handle_from_request_with_session_id(self, discord_channel):
        """Should return session_id when available."""
        mock_request = MagicMock()
        mock_request.session_id = "discord:ch:123"
        mock_request.user_id = "user456"

        to_handle = discord_channel.get_to_handle_from_request(mock_request)

        assert to_handle == "discord:ch:123"

    def test_get_to_handle_from_request_fallback_to_user_id(
        self,
        discord_channel,
    ):
        """Should fallback to user_id when session_id is empty."""
        mock_request = MagicMock()
        mock_request.session_id = ""
        mock_request.user_id = "user789"

        to_handle = discord_channel.get_to_handle_from_request(mock_request)

        assert to_handle == "user789"

    def test_get_to_handle_from_request_empty(self, discord_channel):
        """Should return empty string when both are empty."""
        mock_request = MagicMock()
        mock_request.session_id = ""
        mock_request.user_id = ""

        to_handle = discord_channel.get_to_handle_from_request(mock_request)

        assert to_handle == ""


class TestDiscordChannelToHandleFromTarget:
    """
    P0: Tests for to_handle_from_target method.
    """

    def test_to_handle_from_target_returns_session_id(self, discord_channel):
        """Should return session_id as to_handle."""
        to_handle = discord_channel.to_handle_from_target(
            user_id="user123",
            session_id="discord:ch:456",
        )

        assert to_handle == "discord:ch:456"


# =============================================================================
# P0: Build Agent Request Tests
# =============================================================================


class TestDiscordChannelBuildAgentRequestFromNative:
    """
    P0: Tests for build_agent_request_from_native method.
    """

    def test_build_agent_request_from_native_basic(self, discord_channel):
        """Should build AgentRequest from native payload."""
        native_payload = {
            "channel_id": "discord",
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {"user_id": "user123", "is_dm": True},
        }

        request = discord_channel.build_agent_request_from_native(
            native_payload,
        )

        assert request.user_id == "user123"
        assert request.channel == "discord"
        assert request.channel_meta == {"user_id": "user123", "is_dm": True}
        assert len(request.input) == 1
        assert request.input[0].content[0].text == "Hello"

    def test_build_agent_request_from_native_empty_payload(
        self,
        discord_channel,
    ):
        """Should handle empty/invalid payload."""
        request = discord_channel.build_agent_request_from_native(None)

        # Should still create a request with defaults
        assert request is not None
        assert request.channel == "discord"

    def test_build_agent_request_from_native_with_image(self, discord_channel):
        """Should handle image content in payload."""
        native_payload = {
            "sender_id": "user456",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Look at this"),
                ImageContent(
                    type=ContentType.IMAGE,
                    image_url="http://example.com/img.png",
                ),
            ],
            "meta": {"user_id": "user456"},
        }

        request = discord_channel.build_agent_request_from_native(
            native_payload,
        )

        assert len(request.input[0].content) == 2
        assert request.input[0].content[1].type == ContentType.IMAGE


# =============================================================================
# P1: Async Method Tests
# =============================================================================


class TestDiscordChannelAsyncMethods:
    """
    P1: Tests for async methods.

    Note: Only async test methods use @pytest.mark.asyncio
    """

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, discord_channel_disabled):
        """start() should do nothing when channel is disabled."""
        await discord_channel_disabled.start()

        assert discord_channel_disabled._task is None

    @pytest.mark.asyncio
    async def test_stop_when_disabled(self, discord_channel_disabled):
        """stop() should do nothing when channel is disabled."""
        await discord_channel_disabled.stop()

        # Should complete without error
        assert True

    @pytest.mark.asyncio
    async def test_send_when_disabled(self, discord_channel_disabled):
        """send() should do nothing when channel is disabled."""
        await discord_channel_disabled.send(
            to_handle="discord:ch:123",
            text="Hello",
        )

        # Should complete without error and return None
        assert True

    @pytest.mark.asyncio
    async def test_send_raises_when_client_not_initialized(
        self,
        discord_channel,
    ):
        """send() should raise when client is not initialized."""
        discord_channel.enabled = True
        discord_channel._client = None

        with pytest.raises(
            RuntimeError,
            match="Discord client is not initialized",
        ):
            await discord_channel.send(
                to_handle="discord:ch:123",
                text="Hello",
            )

    @pytest.mark.asyncio
    async def test_send_raises_when_client_not_ready(self, discord_channel):
        """send() should raise when client is not ready."""
        discord_channel.enabled = True
        discord_channel._client = MagicMock()
        discord_channel._client.is_ready = Mock(return_value=False)

        with pytest.raises(RuntimeError, match="Discord client is not ready"):
            await discord_channel.send(
                to_handle="discord:ch:123",
                text="Hello",
            )

    @pytest.mark.asyncio
    async def test_send_media_when_disabled(self, discord_channel_disabled):
        """send_media() should do nothing when channel is disabled."""
        mock_part = MagicMock()
        mock_part.type = ContentType.IMAGE
        mock_part.image_url = "http://example.com/img.png"

        await discord_channel_disabled.send_media(
            to_handle="discord:ch:123",
            part=mock_part,
        )

        # Should complete without error
        assert True

    @pytest.mark.asyncio
    async def test_send_media_skips_when_no_url(self, discord_channel):
        """send_media() should skip when part has no URL."""
        discord_channel.enabled = True
        discord_channel._client = MagicMock()
        discord_channel._client.is_ready = Mock(return_value=True)

        mock_part = MagicMock()
        mock_part.type = ContentType.IMAGE
        mock_part.image_url = None
        mock_part.video_url = None
        mock_part.data = None
        mock_part.file_url = None

        await discord_channel.send_media(
            to_handle="discord:ch:123",
            part=mock_part,
        )

        # Should complete without error
        assert True

    @pytest.mark.asyncio
    async def test_resolve_target_with_channel_id(
        self,
        discord_channel,
        mock_discord_client,
    ):
        """_resolve_target should resolve channel by ID."""
        discord_channel._client = mock_discord_client
        mock_channel = MagicMock()
        mock_discord_client.get_channel = Mock(return_value=mock_channel)

        result = await discord_channel._resolve_target("discord:ch:123456", {})

        assert result == mock_channel
        mock_discord_client.get_channel.assert_called_once_with(123456)

    @pytest.mark.asyncio
    async def test_resolve_target_with_user_id(
        self,
        discord_channel,
        mock_discord_client,
    ):
        """_resolve_target should resolve user DM by ID."""
        discord_channel._client = mock_discord_client
        mock_user = MagicMock()
        mock_dm_channel = MagicMock()
        mock_user.dm_channel = None
        mock_user.create_dm = AsyncMock(return_value=mock_dm_channel)
        mock_discord_client.fetch_user = AsyncMock(return_value=mock_user)

        result = await discord_channel._resolve_target("discord:dm:789012", {})

        assert result == mock_dm_channel


# =============================================================================
# P1: Integration Tests
# =============================================================================


class TestDiscordChannelIntegration:
    """
    P1: Integration tests for Discord channel.
    """

    def test_full_message_flow_resolution(self, discord_channel):
        """Test complete message flow from handle to route and back."""
        # Start with a session handle
        session_handle = "discord:ch:123456"

        # Route from handle
        route = discord_channel._route_from_handle(session_handle)
        assert route == {"channel_id": "123456"}

        # Create a mock request
        mock_request = MagicMock()
        mock_request.session_id = session_handle
        mock_request.user_id = "user789"

        # Get to_handle from request
        to_handle = discord_channel.get_to_handle_from_request(mock_request)
        assert to_handle == session_handle

        # Resolve session ID
        meta = {"is_dm": False, "channel_id": "123456"}
        session_id = discord_channel.resolve_session_id("user789", meta)
        assert session_id == "discord:ch:123456"

    def test_message_chunking_integration(self, discord_channel):
        """Test that message chunking works with various content types."""
        # Create a message with various content
        text_content = "Hello World"
        chunks = discord_channel._chunk_text(text_content)

        assert len(chunks) == 1
        assert chunks[0] == text_content

        # Test with max length message
        long_message = "A" * 1999
        chunks = discord_channel._chunk_text(
            long_message,
            max_len=discord_channel._DISCORD_MAX_LEN,
        )

        assert len(chunks) >= 1
        for chunk in chunks:
            assert len(chunk) <= discord_channel._DISCORD_MAX_LEN


# =============================================================================
# P2: Edge Case Tests
# =============================================================================


class TestDiscordChannelEdgeCases:
    """
    P2: Edge case tests.
    """

    def test_chunk_text_with_only_fences(self):
        """Test chunking text with only code fences."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        text = "```\n```"
        chunks = DiscordChannel._chunk_text(text, max_len=100)

        assert len(chunks) >= 1

    def test_chunk_text_nested_fences(self):
        """Test chunking with nested code fences."""
        from copaw.app.channels.discord_.channel import DiscordChannel

        text = """```python
print("```nested```")
```"""
        chunks = DiscordChannel._chunk_text(text, max_len=100)

        # Should handle the content correctly
        full_text = "\n".join(chunks)
        assert "nested" in full_text

    def test_route_from_handle_with_extra_parts(self, discord_channel):
        """Should handle handles with extra path parts."""
        route = discord_channel._route_from_handle("discord:ch:123:extra")

        # Should still extract the channel_id
        assert route.get("channel_id") == "123"

    def test_resolve_session_id_with_complex_meta(self, discord_channel):
        """Should handle complex meta structures."""
        meta = {
            "is_dm": False,
            "channel_id": "chan123",
            "guild_id": "guild456",
            "message_id": "msg789",
            "extra_data": {"key": "value"},
        }

        session_id = discord_channel.resolve_session_id("user123", meta)

        assert session_id == "discord:ch:chan123"

    def test_build_agent_request_with_empty_content(self, discord_channel):
        """Should handle empty content parts."""
        native_payload = {
            "sender_id": "user123",
            "content_parts": [],
            "meta": {},
        }

        request = discord_channel.build_agent_request_from_native(
            native_payload,
        )

        # Should create request with space as default content
        assert request is not None
        assert len(request.input) == 1

    @pytest.mark.asyncio
    async def test_send_content_parts_empty_list(self, discord_channel):
        """send_content_parts should handle empty list."""
        discord_channel.enabled = False

        # Should not raise
        await discord_channel.send_content_parts(
            to_handle="discord:ch:123",
            parts=[],
        )

    @pytest.mark.asyncio
    async def test_send_content_parts_only_media(self, discord_channel):
        """send_content_parts should handle media-only parts."""
        discord_channel.enabled = False

        mock_part = MagicMock()
        mock_part.type = ContentType.IMAGE
        mock_part.image_url = "http://example.com/img.png"

        # Should not raise
        await discord_channel.send_content_parts(
            to_handle="discord:ch:123",
            parts=[mock_part],
        )
