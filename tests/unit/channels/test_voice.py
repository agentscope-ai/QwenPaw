# -*- coding: utf-8 -*-
"""
Voice Channel Unit Tests

Generated using python-test-pattern skill v0.2.0
Tests cover: initialization, factory methods, lifecycle, core features

Run:
    pytest tests/unit/channels/test_voice.py -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


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
def mock_twilio_manager():
    """Create mock TwilioManager."""
    mgr = MagicMock()
    mgr.configure_voice_webhook = AsyncMock()
    return mgr


@pytest.fixture
def mock_tunnel_manager():
    """Create mock CloudflareTunnelDriver."""
    mgr = MagicMock()
    mgr.start = AsyncMock(
        return_value=MagicMock(
            public_url="https://test-tunnel.example.com",
        ),
    )
    mgr.stop = AsyncMock()
    mgr.get_public_url = Mock(return_value="https://test-tunnel.example.com")
    mgr.get_info = Mock(
        return_value=MagicMock(
            public_url="https://test-tunnel.example.com",
            public_wss_url="wss://test-tunnel.example.com",
        ),
    )
    return mgr


@pytest.fixture
def voice_channel(mock_process):
    """Create VoiceChannel instance for testing."""
    from qwenpaw.app.channels.voice.channel import VoiceChannel

    channel = VoiceChannel(
        process=mock_process,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
    )
    return channel


# =============================================================================
# P0: Initialization Tests
# =============================================================================


class TestVoiceChannelInit:
    """P0: VoiceChannel initialization tests."""

    def test_init_stores_basic_config(self, mock_process):
        """Constructor should store basic configuration parameters."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        channel = VoiceChannel(
            process=mock_process,
            show_tool_details=True,
            filter_tool_messages=True,
            filter_thinking=True,
        )

        assert channel._process == mock_process
        assert channel._show_tool_details is True
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True

    def test_init_creates_required_data_structures(self, mock_process):
        """Constructor should initialize required internal data structures."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        channel = VoiceChannel(process=mock_process)

        # Session manager
        assert hasattr(channel, "session_mgr")
        assert channel.session_mgr is not None

        # Twilio manager (None until from_config)
        assert hasattr(channel, "twilio_mgr")
        assert channel.twilio_mgr is None

        # Tunnel manager
        assert hasattr(channel, "tunnel_mgr")
        assert channel.tunnel_mgr is None

        # Config
        assert hasattr(channel, "_config")
        assert channel._config is None

        # Enabled flag
        assert hasattr(channel, "_enabled")
        assert channel._enabled is False

        # Pending WS tokens
        assert hasattr(channel, "_pending_ws_tokens")
        assert isinstance(channel._pending_ws_tokens, dict)

    def test_channel_type_is_voice(self, voice_channel):
        """Channel type must be 'voice'."""
        assert voice_channel.channel == "voice"

    def test_uses_manager_queue_is_false(self, voice_channel):
        """Voice channel does not use manager queue."""
        assert voice_channel.uses_manager_queue is False


# =============================================================================
# P0: Factory Method Tests
# =============================================================================


class TestVoiceChannelFromConfig:
    """
    P0: Tests for from_config factory method.
    """

    def test_from_config_creates_instance(self, mock_process):
        """from_config should create VoiceChannel instance."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        config = Mock()
        config.enabled = True
        config.twilio_account_sid = "test_sid"
        config.twilio_auth_token = "test_token"
        config.phone_number_sid = "test_phone_sid"
        config.phone_number = "+1234567890"

        channel = VoiceChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert isinstance(channel, VoiceChannel)
        assert channel._config == config
        assert channel._enabled is True

    def test_from_config_stores_basic_params(self, mock_process):
        """from_config should store basic config parameters."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        config = Mock()
        config.enabled = True
        config.twilio_account_sid = "sid_123"
        config.twilio_auth_token = "token_456"

        channel = VoiceChannel.from_config(
            process=mock_process,
            config=config,
            show_tool_details=False,
            filter_tool_messages=True,
            filter_thinking=True,
        )

        assert channel._show_tool_details is False
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True

    def test_from_config_creates_twilio_manager(self, mock_process):
        """from_config creates TwilioManager when credentials provided."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        config = Mock()
        config.enabled = True
        config.twilio_account_sid = "test_sid"
        config.twilio_auth_token = "test_token"
        config.phone_number_sid = "test_phone"

        channel = VoiceChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.twilio_mgr is not None

    def test_from_config_skips_twilio_manager_without_credentials(
        self,
        mock_process,
    ):
        """from_config skips TwilioManager creation without credentials."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        config = Mock()
        config.enabled = True
        config.twilio_account_sid = ""  # Empty
        config.twilio_auth_token = ""  # Empty

        channel = VoiceChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.twilio_mgr is None

    def test_from_config_disabled_channel(self, mock_process):
        """from_config should handle disabled channel."""
        from qwenpaw.app.channels.voice.channel import VoiceChannel

        config = Mock()
        config.enabled = False
        config.twilio_account_sid = "test_sid"
        config.twilio_auth_token = "test_token"

        channel = VoiceChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel._enabled is False


# =============================================================================
# P0: Lifecycle Tests
# =============================================================================


@pytest.mark.asyncio
class TestVoiceChannelLifecycle:
    """
    P0: Tests for channel lifecycle (start/stop).
    """

    async def test_start_when_disabled(self, voice_channel):
        """start() should return early when channel is disabled."""
        voice_channel._enabled = False

        # Should not raise
        await voice_channel.start()

        # No operations performed
        assert voice_channel.tunnel_mgr is None

    async def test_start_without_twilio_manager(self, voice_channel):
        """start() should warn and return without TwilioManager."""
        voice_channel._enabled = True
        voice_channel.twilio_mgr = None

        # Should not raise
        await voice_channel.start()

        # No operations performed
        assert voice_channel.tunnel_mgr is None

    async def test_start_without_phone_number_sid(
        self,
        voice_channel,
        mock_twilio_manager,
    ):
        """start() should warn and return without phone_number_sid."""
        voice_channel._enabled = True
        voice_channel.twilio_mgr = mock_twilio_manager

        config = Mock()
        config.phone_number_sid = ""  # Empty
        voice_channel._config = config

        # Should not raise
        await voice_channel.start()

        assert voice_channel.tunnel_mgr is None

    async def test_start_success(
        self,
        voice_channel,
        mock_twilio_manager,
        mock_tunnel_manager,
    ):
        """start() should successfully start tunnel and configure webhook."""
        voice_channel._enabled = True
        voice_channel.twilio_mgr = mock_twilio_manager

        config = Mock()
        config.phone_number_sid = "phone_123"
        config.phone_number = "+1234567890"
        voice_channel._config = config

        with patch(
            "qwenpaw.tunnel.CloudflareTunnelDriver",
            return_value=mock_tunnel_manager,
        ):
            with patch(
                "qwenpaw.config.utils.read_last_api",
                return_value=("127.0.0.1", 8088),
            ):
                await voice_channel.start()

        # Verify tunnel started
        assert voice_channel.tunnel_mgr == mock_tunnel_manager
        mock_tunnel_manager.start.assert_called_once_with(8088)

        # Verify Twilio webhook configured
        mock_twilio_manager.configure_voice_webhook.assert_called_once()
        call_args = mock_twilio_manager.configure_voice_webhook.call_args
        assert call_args[0][0] == "phone_123"  # phone_number_sid
        assert (
            "https://test-tunnel.example.com/voice/incoming" in call_args[0][1]
        )

    async def test_start_tunnel_failure(
        self,
        voice_channel,
        mock_twilio_manager,
        mock_tunnel_manager,
    ):
        """start() should handle tunnel start failure gracefully."""
        voice_channel._enabled = True
        voice_channel.twilio_mgr = mock_twilio_manager
        voice_channel._config = Mock(phone_number_sid="phone_123")

        mock_tunnel_manager.start = AsyncMock(
            side_effect=Exception("Tunnel failed"),
        )

        with patch(
            "qwenpaw.tunnel.CloudflareTunnelDriver",
            return_value=mock_tunnel_manager,
        ):
            with patch(
                "qwenpaw.config.utils.read_last_api",
                return_value=("127.0.0.1", 8088),
            ):
                # Should not raise
                await voice_channel.start()

        # Note: tunnel_mgr is set before start() is called, so it won't be None
        # but should not continue to Twilio configuration
        assert voice_channel.tunnel_mgr is not None
        # Twilio should not be configured
        mock_twilio_manager.configure_voice_webhook.assert_not_called()

    async def test_start_twilio_config_failure(
        self,
        voice_channel,
        mock_twilio_manager,
        mock_tunnel_manager,
    ):
        """start() should stop tunnel if Twilio config fails."""
        voice_channel._enabled = True
        voice_channel.twilio_mgr = mock_twilio_manager
        voice_channel._config = Mock(phone_number_sid="phone_123")

        mock_twilio_manager.configure_voice_webhook = AsyncMock(
            side_effect=Exception("Twilio failed"),
        )

        with patch(
            "qwenpaw.tunnel.CloudflareTunnelDriver",
            return_value=mock_tunnel_manager,
        ):
            with patch(
                "qwenpaw.config.utils.read_last_api",
                return_value=("127.0.0.1", 8088),
            ):
                # Should not raise
                await voice_channel.start()

        # Tunnel should be stopped
        mock_tunnel_manager.stop.assert_called_once()
        assert voice_channel.tunnel_mgr is None

    async def test_stop_without_start(self, voice_channel):
        """stop() should succeed even without prior start."""
        voice_channel.tunnel_mgr = None

        # Should not raise
        await voice_channel.stop()

    async def test_stop_closes_active_sessions(self, voice_channel):
        """stop() should close all active call sessions."""
        # Create mock session
        mock_session = MagicMock()
        mock_session.call_sid = "call_123"
        mock_session.status = "active"
        mock_session.handler = MagicMock()
        mock_session.handler.close = AsyncMock()

        voice_channel.session_mgr._sessions = {"call_123": mock_session}

        await voice_channel.stop()

        mock_session.handler.close.assert_called_once()
        assert mock_session.status == "ended"

    async def test_stop_stops_tunnel(self, voice_channel, mock_tunnel_manager):
        """stop() should stop the tunnel."""
        voice_channel.tunnel_mgr = mock_tunnel_manager

        await voice_channel.stop()

        mock_tunnel_manager.stop.assert_called_once()


# =============================================================================
# P1: Core Feature Tests
# =============================================================================


@pytest.mark.asyncio
class TestVoiceChannelSend:
    """
    P1: Tests for send method.
    """

    async def test_send_to_active_session(self, voice_channel):
        """send() should send text to active call session."""
        # Create mock session
        mock_session = MagicMock()
        mock_session.status = "active"
        mock_session.handler = MagicMock()
        mock_session.handler.send_text = AsyncMock()

        voice_channel.session_mgr._sessions = {"call_123": mock_session}

        await voice_channel.send("call_123", "Hello", meta={})

        mock_session.handler.send_text.assert_called_once_with("Hello")

    async def test_send_to_inactive_session(self, voice_channel):
        """send() should not send to inactive session."""
        mock_session = MagicMock()
        mock_session.status = "ended"
        mock_session.handler = MagicMock()
        mock_session.handler.send_text = AsyncMock()

        voice_channel.session_mgr._sessions = {"call_123": mock_session}

        await voice_channel.send("call_123", "Hello", meta={})

        mock_session.handler.send_text.assert_not_called()

    async def test_send_to_nonexistent_session(self, voice_channel):
        """send() should handle non-existent session gracefully."""
        # Should not raise
        await voice_channel.send("nonexistent", "Hello", meta={})


class TestVoiceChannelBuildAgentRequest:
    """
    P1: Tests for build_agent_request_from_native.
    """

    def test_build_agent_request_creates_request(self, voice_channel):
        """Should create AgentRequest from voice payload."""
        payload = {
            "transcript": "Hello, this is a test",
            "session_id": "session_123",
            "from_number": "+1234567890",
        }

        request = voice_channel.build_agent_request_from_native(payload)

        assert request.session_id == "session_123"
        assert request.user_id == "+1234567890"
        assert request.channel == "voice"
        assert len(request.input) == 1
        assert request.input[0].content[0].text == "Hello, this is a test"

    def test_build_agent_request_with_empty_transcript(self, voice_channel):
        """Should handle empty transcript."""
        payload = {
            "transcript": "",
            "session_id": "session_123",
            "from_number": "+1234567890",
        }

        request = voice_channel.build_agent_request_from_native(payload)

        assert request.input[0].content[0].text == ""


# =============================================================================
# P2: Utility Method Tests
# =============================================================================


class TestVoiceChannelWebSocketTokens:
    """
    P2: Tests for WebSocket token management.
    """

    def test_create_ws_token_returns_string(self, voice_channel):
        """create_ws_token should return a string token."""
        token = voice_channel.create_ws_token()

        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_ws_token_stores_token(self, voice_channel):
        """create_ws_token should store token in pending list."""
        token = voice_channel.create_ws_token()

        assert token in voice_channel._pending_ws_tokens

    def test_create_ws_token_evicts_old_tokens(self, voice_channel):
        """create_ws_token should evict oldest when exceeding max."""
        # Fill to capacity
        voice_channel._MAX_PENDING_TOKENS = 5
        for _ in range(5):
            voice_channel.create_ws_token()

        old_tokens = list(voice_channel._pending_ws_tokens.keys())

        # Create one more - should evict oldest
        new_token = voice_channel.create_ws_token()

        assert new_token in voice_channel._pending_ws_tokens
        assert old_tokens[0] not in voice_channel._pending_ws_tokens

    def test_validate_ws_token_returns_true_for_valid(self, voice_channel):
        """validate_ws_token should return True for valid token."""
        token = voice_channel.create_ws_token()

        result = voice_channel.validate_ws_token(token)

        assert result is True

    def test_validate_ws_token_removes_token(self, voice_channel):
        """validate_ws_token should remove token after validation."""
        token = voice_channel.create_ws_token()

        voice_channel.validate_ws_token(token)

        assert token not in voice_channel._pending_ws_tokens

    def test_validate_ws_token_returns_false_for_invalid(self, voice_channel):
        """validate_ws_token should return False for invalid token."""
        result = voice_channel.validate_ws_token("invalid_token")

        assert result is False

    def test_validate_ws_token_single_use(self, voice_channel):
        """validate_ws_token should work only once (single-use)."""
        token = voice_channel.create_ws_token()

        first_result = voice_channel.validate_ws_token(token)
        second_result = voice_channel.validate_ws_token(token)

        assert first_result is True
        assert second_result is False


class TestVoiceChannelProperties:
    """
    P2: Tests for properties.
    """

    def test_config_property_returns_config(self, voice_channel):
        """config property should return the config."""
        config = Mock()
        voice_channel._config = config

        result = voice_channel.config

        assert result == config

    def test_process_property_returns_process(
        self,
        voice_channel,
        mock_process,
    ):
        """process property should return the process handler."""
        result = voice_channel.process

        assert result == mock_process

    def test_get_tunnel_url_with_manager(
        self,
        voice_channel,
        mock_tunnel_manager,
    ):
        """get_tunnel_url should return URL when tunnel exists."""
        voice_channel.tunnel_mgr = mock_tunnel_manager

        result = voice_channel.get_tunnel_url()

        assert result == "https://test-tunnel.example.com"

    def test_get_tunnel_url_without_manager(self, voice_channel):
        """get_tunnel_url should return None without tunnel."""
        voice_channel.tunnel_mgr = None

        result = voice_channel.get_tunnel_url()

        assert result is None

    def test_get_tunnel_wss_url_with_manager(
        self,
        voice_channel,
        mock_tunnel_manager,
    ):
        """get_tunnel_wss_url should return WSS URL when tunnel exists."""
        voice_channel.tunnel_mgr = mock_tunnel_manager

        result = voice_channel.get_tunnel_wss_url()

        assert result == "wss://test-tunnel.example.com"

    def test_get_tunnel_wss_url_without_manager(self, voice_channel):
        """get_tunnel_wss_url should return None without tunnel."""
        voice_channel.tunnel_mgr = None

        result = voice_channel.get_tunnel_wss_url()

        assert result is None

    def test_get_tunnel_wss_url_with_no_info(
        self,
        voice_channel,
        mock_tunnel_manager,
    ):
        """get_tunnel_wss_url should return None when get_info returns None."""
        mock_tunnel_manager.get_info = Mock(return_value=None)
        voice_channel.tunnel_mgr = mock_tunnel_manager

        result = voice_channel.get_tunnel_wss_url()

        assert result is None
