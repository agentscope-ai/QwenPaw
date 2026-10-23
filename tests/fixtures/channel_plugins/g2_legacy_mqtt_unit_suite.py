"""Preserved MQTT constructor and required-config assertions on Platform."""

from pathlib import Path
import sys
import socket

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/mqtt"))
from qwenpaw_channel_mqtt.platform import MQTTPlatform


async def unused_callback(_value):
    raise AssertionError("Invalid/static platform test emitted an event")


@pytest.mark.parametrize(
    "config",
    [
        {
            "enabled": True,
            "host": "mqtt.example.com",
            "port": 8883,
            "transport": "tcp",
            "username": "user123",
            "password": "secret",
            "subscribe_topic": "in/+/test",
            "publish_topic": "out/+/test",
            "bot_prefix": "[MQTT] ",
        },
        {
            "enabled": True,
            "host": "mqtt.example.com",
            "port": 1883,
            "transport": "tcp",
            "username": "",
            "password": "",
            "subscribe_topic": "test/in",
            "publish_topic": "test/out",
            "bot_prefix": "",
            "clean_session": False,
            "qos": 1,
            "tls_enabled": True,
            "tls_ca_certs": "/path/to/ca.crt",
            "tls_certfile": "/path/to/client.crt",
            "tls_keyfile": "/path/to/client.key",
        },
    ],
)
def test_original_basic_and_advanced_values_remain_owned_config(config):
    platform = MQTTPlatform(dict(config), unused_callback, unused_callback)
    assert platform.config == config
    assert platform.client is None and platform.connected is False
    assert platform._tasks == platform._publishes == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing", ["host", "subscribe_topic", "publish_topic"]
)
async def test_missing_required_config_fails_before_sdk_connection(missing):
    config = {
        "host": "127.0.0.1",
        "subscribe_topic": "in/+",
        "publish_topic": "out/{client_id}",
    }
    config[missing] = ""
    platform = MQTTPlatform(config, unused_callback, unused_callback)
    with pytest.raises(ValueError, match=missing + " is required"):
        await platform.start()
    assert platform.client is None and platform.connected is False


@pytest.mark.asyncio
async def test_stop_without_sdk_client_is_complete_and_idempotent():
    platform = MQTTPlatform({}, unused_callback, unused_callback)
    await platform.stop()
    await platform.stop()
    assert platform.client is None and not platform.connected
    assert platform._tasks == platform._publishes == set()


@pytest.mark.asyncio
async def test_start_connect_failure_never_starts_sdk_loop():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    platform = MQTTPlatform(
        {
            "host": "127.0.0.1",
            "port": port,
            "subscribe_topic": "test/topic",
            "publish_topic": "out/{client_id}",
        },
        unused_callback,
        unused_callback,
    )
    try:
        with pytest.raises(ConnectionRefusedError):
            await platform.start()
        assert platform.client is not None and platform.client._thread is None
        assert not platform.connected
    finally:
        await platform.stop()
    assert platform.client is None
