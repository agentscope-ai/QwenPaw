# -*- coding: utf-8 -*-
"""
MQTT Channel Unit Tests

Generated using python-test-pattern skill v0.2.0
Tests cover: initialization, factory methods, lifecycle, message handling

Run:
    pytest tests/unit/channels/test_mqtt.py -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

import json
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
def mock_mqtt_client():
    """Create mock MQTT client."""
    client = MagicMock()
    client.username_pw_set = Mock()
    client.tls_set = Mock()
    client.connect = Mock()
    client.loop_start = Mock()
    client.loop_stop = Mock()
    client.disconnect = Mock()
    client.subscribe = Mock()
    client.publish = Mock()
    client.reconnect_delay_set = Mock()
    return client


@pytest.fixture
def mqtt_channel(mock_process):
    """Create MQTTChannel instance for testing."""
    from qwenpaw.app.channels.mqtt.channel import MQTTChannel

    channel = MQTTChannel(
        process=mock_process,
        enabled=True,
        host="test.mqtt.local",
        port=1883,
        transport="tcp",
        username="test_user",
        password="test_pass",
        subscribe_topic="copaw/in/{client_id}",
        publish_topic="copaw/out/{client_id}",
        bot_prefix="[BOT] ",
        clean_session=True,
        qos=2,
        tls_enabled=False,
    )
    return channel


# =============================================================================
# P0: Initialization Tests
# =============================================================================


class TestMQTTChannelInit:
    """
    P0: MQTTChannel initialization tests.
    """

    def test_init_stores_basic_config(self, mock_process):
        """Constructor should store all basic configuration parameters."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        channel = MQTTChannel(
            process=mock_process,
            enabled=True,
            host="mqtt.example.com",
            port=8883,
            transport="tcp",
            username="user123",
            password="secret",
            subscribe_topic="in/+/test",
            publish_topic="out/+/test",
            bot_prefix="[MQTT] ",
        )

        assert channel.enabled is True
        assert channel.host == "mqtt.example.com"
        assert channel.port == 8883
        assert channel.transport == "tcp"
        assert channel.username == "user123"
        assert channel.password == "secret"
        assert channel.subscribe_topic == "in/+/test"
        assert channel.publish_topic == "out/+/test"
        assert channel.bot_prefix == "[MQTT] "

    def test_init_stores_advanced_config(self, mock_process):
        """Constructor should store advanced configuration parameters."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        channel = MQTTChannel(
            process=mock_process,
            enabled=True,
            host="mqtt.example.com",
            port=1883,
            transport="tcp",
            username="",
            password="",
            subscribe_topic="test/in",
            publish_topic="test/out",
            bot_prefix="",
            clean_session=False,
            qos=1,
            tls_enabled=True,
            tls_ca_certs="/path/to/ca.crt",
            tls_certfile="/path/to/client.crt",
            tls_keyfile="/path/to/client.key",
        )

        assert channel.clean_session is False
        assert channel.qos == 1
        assert channel.tls_enabled is True
        assert channel.tls_ca_certs == "/path/to/ca.crt"
        assert channel.tls_certfile == "/path/to/client.crt"
        assert channel.tls_keyfile == "/path/to/client.key"

    def test_init_creates_required_data_structures(self, mock_process):
        """Constructor should initialize required internal data structures."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        channel = MQTTChannel(
            process=mock_process,
            enabled=True,
            host="test.host",
            port=1883,
            transport="tcp",
            username="",
            password="",
            subscribe_topic="test/in",
            publish_topic="test/out",
            bot_prefix="",
        )

        assert hasattr(channel, "client")
        assert channel.client is None
        assert hasattr(channel, "connected")
        assert channel.connected is False

    def test_channel_type_is_mqtt(self, mqtt_channel):
        """Channel type must be 'mqtt'."""
        assert mqtt_channel.channel == "mqtt"

    def test_uses_manager_queue_is_true(self, mqtt_channel):
        """MQTT channel uses manager queue."""
        assert mqtt_channel.uses_manager_queue is True


# =============================================================================
# P0: Factory Method Tests
# =============================================================================


class TestMQTTChannelFromEnv:
    """
    P0: Tests for from_env factory method.
    """

    def test_from_env_reads_basic_env_vars(self, mock_process, monkeypatch):
        """from_env should read basic environment variables."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        monkeypatch.setenv("MQTT_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("MQTT_HOST", "env.mqtt.local")
        monkeypatch.setenv("MQTT_PORT", "8883")
        monkeypatch.setenv("MQTT_TRANSPORT", "websockets")
        monkeypatch.setenv("MQTT_USERNAME", "env_user")
        monkeypatch.setenv("MQTT_PASSWORD", "env_pass")
        monkeypatch.setenv("MQTT_SUBSCRIBE_TOPIC", "env/in")
        monkeypatch.setenv("MQTT_PUBLISH_TOPIC", "env/out")
        monkeypatch.setenv("MQTT_BOT_PREFIX", "[ENV] ")

        channel = MQTTChannel.from_env(mock_process)

        assert channel.enabled is True
        assert channel.host == "env.mqtt.local"
        assert channel.port == 8883
        assert channel.transport == "websockets"
        assert channel.username == "env_user"
        assert channel.password == "env_pass"
        assert channel.subscribe_topic == "env/in"
        assert channel.publish_topic == "env/out"
        assert channel.bot_prefix == "[ENV] "

    def test_from_env_reads_advanced_env_vars(self, mock_process, monkeypatch):
        """from_env should read advanced environment variables."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        monkeypatch.setenv("MQTT_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("MQTT_HOST", "test.mqtt.local")
        monkeypatch.setenv("MQTT_CLEAN_SESSION", "0")
        monkeypatch.setenv("MQTT_QOS", "1")
        monkeypatch.setenv("MQTT_TLS_ENABLED", "1")
        monkeypatch.setenv("MQTT_TLS_CA_CERTS", "/path/to/ca")
        monkeypatch.setenv("MQTT_TLS_CERTFILE", "/path/to/cert")
        monkeypatch.setenv("MQTT_TLS_KEYFILE", "/path/to/key")

        channel = MQTTChannel.from_env(mock_process)

        assert channel.clean_session is False
        assert channel.qos == 1
        assert channel.tls_enabled is True
        assert channel.tls_ca_certs == "/path/to/ca"
        assert channel.tls_certfile == "/path/to/cert"
        assert channel.tls_keyfile == "/path/to/key"

    def test_from_env_defaults(self, mock_process, monkeypatch):
        """from_env should use sensible defaults."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        monkeypatch.setenv("MQTT_HOST", "test.mqtt.local")
        monkeypatch.setenv("MQTT_SUBSCRIBE_TOPIC", "test/in")
        monkeypatch.setenv("MQTT_PUBLISH_TOPIC", "test/out")

        # Clear optional env vars
        monkeypatch.delenv("MQTT_PORT", raising=False)
        monkeypatch.delenv("MQTT_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("MQTT_CLEAN_SESSION", raising=False)
        monkeypatch.delenv("MQTT_QOS", raising=False)
        monkeypatch.delenv("MQTT_TLS_ENABLED", raising=False)

        channel = MQTTChannel.from_env(mock_process)

        assert channel.enabled is False  # Default off
        assert channel.port == 1883  # Default port
        assert channel.clean_session is True  # Default
        assert channel.qos == 2  # Default
        assert channel.tls_enabled is False  # Default

    def test_from_env_invalid_port_defaults_to_1883(
        self,
        mock_process,
        monkeypatch,
    ):
        """from_env should handle invalid port."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        monkeypatch.setenv("MQTT_HOST", "test.mqtt.local")
        monkeypatch.setenv("MQTT_SUBSCRIBE_TOPIC", "test/in")
        monkeypatch.setenv("MQTT_PUBLISH_TOPIC", "test/out")
        monkeypatch.setenv("MQTT_PORT", "invalid")

        channel = MQTTChannel.from_env(mock_process)

        assert channel.port == 1883  # Falls back to default


class TestMQTTChannelFromConfig:
    """
    P0: Tests for from_config factory method.
    """

    def test_from_config_with_dict(self, mock_process):
        """from_config should accept dict config."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        config = {
            "enabled": True,
            "host": "dict.mqtt.local",
            "port": "1883",
            "username": "dict_user",
            "password": "dict_pass",
            "subscribe_topic": "dict/in",
            "publish_topic": "dict/out",
            "bot_prefix": "[DICT] ",
            "clean_session": False,
            "qos": "0",
            "transport": "websockets",
        }

        channel = MQTTChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is True
        assert channel.host == "dict.mqtt.local"
        assert channel.port == 1883
        assert channel.username == "dict_user"
        assert channel.clean_session is False
        assert channel.qos == 0
        assert channel.transport == "websockets"

    def test_from_config_with_object(self, mock_process):
        """from_config should accept config object."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        config = Mock()
        config.enabled = True
        config.host = "obj.mqtt.local"
        config.port = 8883
        config.username = "obj_user"
        config.password = "obj_pass"
        config.subscribe_topic = "obj/in"
        config.publish_topic = "obj/out"
        config.bot_prefix = "[OBJ] "
        config.clean_session = True
        config.qos = 2
        config.transport = "tcp"
        config.tls_enabled = False
        config.tls_ca_certs = None
        config.tls_certfile = None
        config.tls_keyfile = None

        channel = MQTTChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.host == "obj.mqtt.local"
        assert channel.port == 8883

    def test_from_config_strips_whitespace(self, mock_process):
        """from_config should strip whitespace from string values."""
        from qwenpaw.app.channels.mqtt.channel import MQTTChannel

        config = {
            "host": "  spaced.host  ",
            "subscribe_topic": "  spaced/in  ",
            "publish_topic": "  spaced/out  ",
        }

        channel = MQTTChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.host == "spaced.host"
        assert channel.subscribe_topic == "spaced/in"
        assert channel.publish_topic == "spaced/out"


# =============================================================================
# P0: Configuration Validation Tests
# =============================================================================


class TestMQTTChannelConfigValidation:
    """
    P0: Tests for configuration validation.
    """

    def test_validate_config_missing_host_raises(self, mqtt_channel):
        """_validate_config should raise when host is missing."""
        mqtt_channel.host = ""

        with pytest.raises(ValueError, match="MQTT host is required"):
            mqtt_channel._validate_config()

    def test_validate_config_missing_subscribe_topic_raises(
        self,
        mqtt_channel,
    ):
        """_validate_config should raise when subscribe_topic is missing."""
        mqtt_channel.subscribe_topic = ""

        with pytest.raises(
            ValueError,
            match="MQTT subscribe_topic is required",
        ):
            mqtt_channel._validate_config()

    def test_validate_config_missing_publish_topic_raises(self, mqtt_channel):
        """_validate_config should raise when publish_topic is missing."""
        mqtt_channel.publish_topic = ""

        with pytest.raises(ValueError, match="MQTT publish_topic is required"):
            mqtt_channel._validate_config()

    def test_validate_config_valid_passes(self, mqtt_channel):
        """_validate_config should pass with valid config."""
        # Should not raise
        mqtt_channel._validate_config()


# =============================================================================
# P0: Lifecycle Tests
# =============================================================================


@pytest.mark.asyncio
class TestMQTTChannelLifecycle:
    """
    P0: Tests for channel lifecycle (start/stop).
    """

    async def test_start_when_disabled(self, mqtt_channel):
        """start() should return early when channel is disabled."""
        mqtt_channel.enabled = False

        # Should not raise
        await mqtt_channel.start()

        assert mqtt_channel.client is None

    async def test_start_with_invalid_config(self, mqtt_channel):
        """start() should return early when config is invalid."""
        mqtt_channel.host = ""  # Will fail validation

        # Should not raise
        await mqtt_channel.start()

        assert mqtt_channel.client is None

    async def test_start_success(self, mqtt_channel, mock_mqtt_client):
        """start() should successfully create and connect MQTT client."""
        with patch(
            "qwenpaw.app.channels.mqtt.channel.mqtt.Client",
            return_value=mock_mqtt_client,
        ):
            await mqtt_channel.start()

        assert mqtt_channel.client == mock_mqtt_client
        mock_mqtt_client.username_pw_set.assert_called_once_with(
            "test_user",
            "test_pass",
        )
        mock_mqtt_client.reconnect_delay_set.assert_called_once_with(
            min_delay=1,
            max_delay=10,
        )
        mock_mqtt_client.connect.assert_called_once_with(
            "test.mqtt.local",
            1883,
            keepalive=60,
        )
        mock_mqtt_client.loop_start.assert_called_once()

    async def test_start_with_tls(self, mqtt_channel, mock_mqtt_client):
        """start() should configure TLS when enabled."""
        mqtt_channel.tls_enabled = True
        mqtt_channel.tls_ca_certs = "/path/to/ca.crt"
        mqtt_channel.tls_certfile = "/path/to/client.crt"
        mqtt_channel.tls_keyfile = "/path/to/client.key"

        with patch(
            "qwenpaw.app.channels.mqtt.channel.mqtt.Client",
            return_value=mock_mqtt_client,
        ):
            await mqtt_channel.start()

        mock_mqtt_client.tls_set.assert_called_once_with(
            ca_certs="/path/to/ca.crt",
            certfile="/path/to/client.crt",
            keyfile="/path/to/client.key",
        )

    async def test_start_without_auth(self, mqtt_channel, mock_mqtt_client):
        """start() should skip auth when credentials not provided."""
        mqtt_channel.username = ""
        mqtt_channel.password = ""

        with patch(
            "qwenpaw.app.channels.mqtt.channel.mqtt.Client",
            return_value=mock_mqtt_client,
        ):
            await mqtt_channel.start()

        mock_mqtt_client.username_pw_set.assert_not_called()

    async def test_start_connect_failure(self, mqtt_channel, mock_mqtt_client):
        """start() should handle connection failure gracefully."""
        from paho.mqtt import MQTTException

        mock_mqtt_client.connect = Mock(
            side_effect=MQTTException("Connection refused"),
        )

        with patch(
            "qwenpaw.app.channels.mqtt.channel.mqtt.Client",
            return_value=mock_mqtt_client,
        ):
            # Should not raise
            await mqtt_channel.start()

        # Client should be created but loop not started
        mock_mqtt_client.loop_start.assert_not_called()

    async def test_stop_success(self, mqtt_channel, mock_mqtt_client):
        """stop() should stop client and disconnect."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        await mqtt_channel.stop()

        mock_mqtt_client.loop_stop.assert_called_once()
        mock_mqtt_client.disconnect.assert_called_once()
        assert mqtt_channel.client is None
        assert mqtt_channel.connected is False

    async def test_stop_without_client(self, mqtt_channel):
        """stop() should handle no client gracefully."""
        mqtt_channel.client = None

        # Should not raise
        await mqtt_channel.stop()


# =============================================================================
# P1: Callback Tests
# =============================================================================


class TestMQTTChannelCallbacks:
    """
    P1: Tests for MQTT callbacks.
    """

    def test_on_connect_success(self, mqtt_channel):
        """_on_connect should set connected flag and subscribe on success."""
        mock_client = MagicMock()
        mqtt_channel.subscribe_topic = "test/topic"
        mqtt_channel.qos = 2

        mqtt_channel._on_connect(mock_client, None, None, 0, None)

        assert mqtt_channel.connected is True
        mock_client.subscribe.assert_called_once_with("test/topic", qos=2)

    def test_on_connect_failure(self, mqtt_channel):
        """_on_connect should handle connection failure."""
        mock_client = MagicMock()

        mqtt_channel._on_connect(mock_client, None, None, 5, None)

        assert mqtt_channel.connected is False
        mock_client.subscribe.assert_not_called()

    def test_on_disconnect_normal(self, mqtt_channel):
        """_on_disconnect should clear connected flag."""
        mqtt_channel.connected = True

        mqtt_channel._on_disconnect(None, None, None, 0, None)

        assert mqtt_channel.connected is False

    def test_on_disconnect_unexpected(self, mqtt_channel):
        """_on_disconnect clears connected flag on unexpected disconnect."""
        mqtt_channel.connected = True

        mqtt_channel._on_disconnect(None, None, None, 1, None)

        assert mqtt_channel.connected is False


# =============================================================================
# P1: Message Handling Tests
# =============================================================================


class TestMQTTChannelMessageHandling:
    """
    P1: Tests for message processing.
    """

    def test_on_message_json_payload_with_explicit_client_id(
        self,
        mqtt_channel,
    ):
        """_on_message should use client_id from JSON payload if present."""
        mock_msg = MagicMock()
        mock_msg.topic = "copaw/in/ignored-topic-client"
        mock_msg.payload = json.dumps(
            {
                "text": "Hello MQTT",
                "redirect_client_id": "explicit-client-123",
            },
        ).encode()

        mock_enqueue = Mock()
        mqtt_channel._enqueue = mock_enqueue

        mqtt_channel._on_message(None, None, mock_msg)

        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args[0][0]
        assert call_args["sender_id"] == "explicit-client-123"
        assert call_args["content_parts"][0].text == "Hello MQTT"

    def test_on_message_plaintext_payload(self, mqtt_channel):
        """_on_message should handle non-JSON payload."""
        mock_msg = MagicMock()
        mock_msg.topic = "copaw/in/test-client"
        mock_msg.payload = b"Plain text message"

        mock_enqueue = Mock()
        mqtt_channel._enqueue = mock_enqueue

        mqtt_channel._on_message(None, None, mock_msg)

        call_args = mock_enqueue.call_args[0][0]
        assert call_args["content_parts"][0].text == "Plain text message"

    def test_on_message_extracts_client_id_from_topic(self, mqtt_channel):
        """_on_message extracts client_id from topic path."""
        mock_msg = MagicMock()
        mock_msg.topic = "copaw/in/my-device-001"
        mock_msg.payload = b"Hello"  # No redirect_client_id in payload

        mock_enqueue = Mock()
        mqtt_channel._enqueue = mock_enqueue

        mqtt_channel._on_message(None, None, mock_msg)

        call_args = mock_enqueue.call_args[0][0]
        # Topic "copaw/in/my-device-001"
        # parts[1] = "in"
        assert call_args["sender_id"] == "in"

    def test_on_message_empty_content_skipped(self, mqtt_channel):
        """_on_message should skip empty/whitespace-only content."""
        mock_msg = MagicMock()
        mock_msg.topic = "test/topic"
        mock_msg.payload = b"   "  # Whitespace only

        mock_enqueue = Mock()
        mqtt_channel._enqueue = mock_enqueue

        mqtt_channel._on_message(None, None, mock_msg)

        mock_enqueue.assert_not_called()

    def test_on_message_no_enqueue_handles_gracefully(self, mqtt_channel):
        """_on_message should handle missing _enqueue gracefully."""
        mock_msg = MagicMock()
        mock_msg.topic = "copaw/in/test-client"
        mock_msg.payload = b"Test message"

        mqtt_channel._enqueue = None

        # Should not raise
        mqtt_channel._on_message(None, None, mock_msg)

    def test_on_message_exception_handled(self, mqtt_channel):
        """_on_message should handle exceptions gracefully (not raise)."""
        mock_msg = MagicMock()
        mock_msg.topic = "test/topic"
        # Invalid bytes that can't be decoded as UTF-8
        mock_msg.payload = b"\xff\xfe\x00\x01"

        # Should not raise
        mqtt_channel._on_message(None, None, mock_msg)


# =============================================================================
# P1: Send Tests
# =============================================================================


@pytest.mark.asyncio
class TestMQTTChannelSend:
    """
    P1: Tests for send methods.
    """

    async def test_send_success(self, mqtt_channel, mock_mqtt_client):
        """send() should publish message to formatted topic."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        await mqtt_channel.send("device-001", "Hello device", meta={})

        mock_mqtt_client.publish.assert_called_once_with(
            "copaw/out/device-001",
            "Hello device",
            qos=2,
        )

    async def test_send_with_meta_client_id(
        self,
        mqtt_channel,
        mock_mqtt_client,
    ):
        """send() should use client_id from meta."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        await mqtt_channel.send(
            "ignored-handle",
            "Hello",
            meta={"client_id": "real-device"},
        )

        mock_mqtt_client.publish.assert_called_once_with(
            "copaw/out/real-device",
            "Hello",
            qos=mqtt_channel.qos,
        )

    async def test_send_disabled_does_nothing(
        self,
        mqtt_channel,
        mock_mqtt_client,
    ):
        """send() should do nothing when disabled."""
        mqtt_channel.enabled = False
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        await mqtt_channel.send("device", "Hello", meta={})

        mock_mqtt_client.publish.assert_not_called()

    async def test_send_not_connected_does_nothing(
        self,
        mqtt_channel,
        mock_mqtt_client,
    ):
        """send() should do nothing when not connected."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = False

        await mqtt_channel.send("device", "Hello", meta={})

        mock_mqtt_client.publish.assert_not_called()

    async def test_send_no_client_id_does_nothing(
        self,
        mqtt_channel,
        mock_mqtt_client,
    ):
        """send() should do nothing when no client_id provided."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        await mqtt_channel.send("", "Hello", meta={})

        mock_mqtt_client.publish.assert_not_called()

    async def test_send_media_success(self, mqtt_channel, mock_mqtt_client):
        """send_media() should handle image content."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        from qwenpaw.app.channels.base import ImageContent, ContentType

        mock_part = ImageContent(
            type=ContentType.IMAGE,
            image_url="http://img.jpg",
        )

        await mqtt_channel.send_media("device-001", mock_part, meta={})

        mock_mqtt_client.publish.assert_called_once_with(
            "copaw/out/device-001",
            "[Image] http://img.jpg",
            qos=mqtt_channel.qos,
        )

    async def test_send_media_video(self, mqtt_channel, mock_mqtt_client):
        """send_media() should handle video content."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        from qwenpaw.app.channels.base import VideoContent, ContentType

        mock_part = VideoContent(
            type=ContentType.VIDEO,
            video_url="http://vid.mp4",
        )

        await mqtt_channel.send_media("device-001", mock_part, meta={})

        mock_mqtt_client.publish.assert_called_once_with(
            "copaw/out/device-001",
            "[Video] http://vid.mp4",
            qos=mqtt_channel.qos,
        )

    async def test_send_media_file(self, mqtt_channel, mock_mqtt_client):
        """send_media() should handle file content."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        from qwenpaw.app.channels.base import FileContent, ContentType

        mock_part = FileContent(
            type=ContentType.FILE,
            file_url="http://doc.pdf",
        )

        await mqtt_channel.send_media("device-001", mock_part, meta={})

        mock_mqtt_client.publish.assert_called_once_with(
            "copaw/out/device-001",
            "[File] http://doc.pdf",
            qos=mqtt_channel.qos,
        )

    async def test_send_media_audio(self, mqtt_channel, mock_mqtt_client):
        """send_media() should handle audio content."""
        mqtt_channel.client = mock_mqtt_client
        mqtt_channel.connected = True

        from qwenpaw.app.channels.base import AudioContent, ContentType

        mock_part = AudioContent(
            type=ContentType.AUDIO,
            audio_url="http://audio.mp3",
        )

        await mqtt_channel.send_media("device-001", mock_part, meta={})

        mock_mqtt_client.publish.assert_called_once_with(
            "copaw/out/device-001",
            "[Audio]",
            qos=mqtt_channel.qos,
        )


# =============================================================================
# P2: Utility Method Tests
# =============================================================================


class TestMQTTChannelUtilities:
    """
    P2: Tests for utility methods.
    """

    def test_resolve_session_id(self, mqtt_channel):
        """resolve_session_id should format session ID."""
        result = mqtt_channel.resolve_session_id("device-001", {})

        assert result == "mqtt:device-001"

    def test_get_to_handle_from_request_with_meta(self, mqtt_channel):
        """get_to_handle_from_request should extract from meta."""
        mock_request = Mock()
        mock_request.channel_meta = {"client_id": "meta-device"}
        mock_request.session_id = "mqtt:session-device"

        result = mqtt_channel.get_to_handle_from_request(mock_request)

        assert result == "meta-device"

    def test_get_to_handle_from_request_from_session(self, mqtt_channel):
        """get_to_handle_from_request should extract from session_id."""
        mock_request = Mock()
        mock_request.channel_meta = {}
        mock_request.session_id = "mqtt:session-device"

        result = mqtt_channel.get_to_handle_from_request(mock_request)

        assert result == "session-device"

    def test_get_to_handle_from_request_from_user_id(self, mqtt_channel):
        """get_to_handle_from_request should fallback to user_id."""
        mock_request = Mock()
        mock_request.channel_meta = {}
        mock_request.session_id = "other-session"
        mock_request.user_id = "fallback-user"

        result = mqtt_channel.get_to_handle_from_request(mock_request)

        assert result == "fallback-user"

    def test_build_agent_request_from_native(self, mqtt_channel):
        """build_agent_request_from_native should create proper request."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            TextContent,
            ContentType,
        )

        payload = {
            "channel_id": "mqtt",
            "sender_id": "device-001",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {"client_id": "real-device"},
        }

        request = mqtt_channel.build_agent_request_from_native(payload)

        assert request.user_id == "real-device"
        assert request.channel == "mqtt"
        assert request.channel_meta["client_id"] == "real-device"

    def test_to_handle_from_target_with_session(self, mqtt_channel):
        """to_handle_from_target should extract from session_id."""
        result = mqtt_channel.to_handle_from_target(
            user_id="ignored",
            session_id="mqtt:real-device",
        )

        assert result == "real-device"

    def test_to_handle_from_target_without_session(self, mqtt_channel):
        """to_handle_from_target should use user_id."""
        result = mqtt_channel.to_handle_from_target(
            user_id="device-001",
            session_id="other-session",
        )

        assert result == "device-001"
