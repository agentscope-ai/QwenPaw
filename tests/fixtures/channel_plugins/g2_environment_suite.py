"""Environment compatibility through the public ChannelManager factory."""

import json
from pathlib import Path
import sys
from types import MappingProxyType

import pytest

from extension_admission_suite import registry
from extension_sample import ROOT, sample_source
from g2_official_process_suite import official_source, forbid_host_sdk_import


async def unused_process(_request):
    raise AssertionError("Environment discovery ran the Agent")
    yield


def register_source(registry, source):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import (
        ChannelRuntimeSettings,
        describe_channel,
    )

    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text())
    )
    description = describe_channel(source, manifest)
    registry.register_channel_descriptor(
        manifest.id,
        description,
        runtime_settings=ChannelRuntimeSettings(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            qwenpaw_version="2.2.2b4",
            selected_channels=None,
        ),
    )
    return description


@pytest.mark.asyncio
async def test_from_env_keeps_enabled_descriptor_without_channel_class(
    tmp_path, monkeypatch, registry
):
    """Expose the class-only loop without assuming any new env-reader API."""
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
    from qwenpaw.config import get_available_channels

    source = sample_source(tmp_path)
    path = source / "channel.json"
    descriptor = json.loads(path.read_text())
    descriptor["config_schema"]["properties"]["enabled"]["default"] = True
    path.write_text(json.dumps(descriptor))
    register_source(registry, source)
    monkeypatch.setenv("QWENPAW_ENABLED_CHANNELS", "sample_chat")
    assert get_available_channels() == ("sample_chat",)
    assert (
        registry.get_channel_registration("sample_chat").channel_class is None
    )
    manager = ChannelManager.from_env(unused_process)
    channel = await manager.get_channel("sample_chat")
    assert isinstance(
        channel, IsolatedChannelProxy
    ), "from_env silently dropped the descriptor-only channel"
    assert channel._launch_spec.config["enabled"] is True
    assert channel._launch_spec.code_root == source
    assert channel.channel_process.health_snapshot()["pid"] is None


ENV_CASES = [
    (
        "mqtt",
        {
            "MQTT_HOST": "env.mqtt.local",
            "MQTT_PORT": "8883",
            "MQTT_TRANSPORT": "websockets",
            "MQTT_USERNAME": "env_user",
            "MQTT_PASSWORD": "env_pass",
            "MQTT_SUBSCRIBE_TOPIC": "env/in",
            "MQTT_PUBLISH_TOPIC": "env/out",
            "MQTT_BOT_PREFIX": "[ENV] ",
        },
        {
            "enabled": True,
            "host": "env.mqtt.local",
            "port": 8883,
            "transport": "websockets",
            "username": "env_user",
            "password": "env_pass",
            "subscribe_topic": "env/in",
            "publish_topic": "env/out",
            "bot_prefix": "[ENV] ",
        },
    ),
    (
        "mattermost",
        {
            "MATTERMOST_URL": "https://env.mm.com",
            "MATTERMOST_BOT_TOKEN": "env_token_123",
            "MATTERMOST_BOT_PREFIX": "[EnvBot] ",
        },
        {
            "enabled": True,
            "url": "https://env.mm.com",
            "bot_token": "env_token_123",
            "bot_prefix": "[EnvBot] ",
        },
    ),
    (
        "mqtt",
        {},
        {
            "port": 1883,
            "qos": 2,
            "transport": "mqtt",
            "clean_session": True,
            "tls_enabled": False,
        },
    ),
    (
        "mqtt",
        {"MQTT_PORT": "invalid", "MQTT_QOS": "invalid"},
        {"port": 1883, "qos": 0},
    ),
    (
        "mqtt",
        {
            "MQTT_PORT": "8883",
            "MQTT_QOS": "1",
            "MQTT_TRANSPORT": "websockets",
            "MQTT_CLEAN_SESSION": "0",
            "MQTT_TLS_ENABLED": "1",
            "MQTT_TLS_CA_CERTS": "/ca.pem",
            "MQTT_TLS_CERTFILE": "/client.pem",
            "MQTT_TLS_KEYFILE": "/client.key",
            "MQTT_USERNAME": "user",
            "MQTT_PASSWORD": "password",
        },
        {
            "port": 8883,
            "qos": 1,
            "transport": "websockets",
            "clean_session": False,
            "tls_enabled": True,
            "tls_ca_certs": "/ca.pem",
            "tls_certfile": "/client.pem",
            "tls_keyfile": "/client.key",
            "username": "user",
            "password": "password",
        },
    ),
    (
        "mqtt",
        {
            "MQTT_HOST": "  mqtt.example  ",
            "MQTT_USERNAME": " user ",
            "MQTT_BOT_PREFIX": " [BOT] ",
        },
        {
            "host": "  mqtt.example  ",
            "username": " user ",
            "bot_prefix": " [BOT] ",
        },
    ),
    (
        "mattermost",
        {},
        {
            "show_typing": True,
            "thread_follow_without_mention": False,
            "allow_from": [],
            "dm_policy": "open",
            "group_policy": "open",
        },
    ),
    (
        "mattermost",
        {
            "MATTERMOST_URL": "https://mattermost.example///",
            "MATTERMOST_ALLOW_FROM": " alice, , bob ",
            "MATTERMOST_SHOW_TYPING": "0",
            "MATTERMOST_THREAD_FOLLOW": "1",
            "MATTERMOST_DM_POLICY": "allowlist",
            "MATTERMOST_GROUP_POLICY": "allowlist",
            "MATTERMOST_DENY_MESSAGE": "Denied",
            "MATTERMOST_MEDIA_DIR": "~/media",
        },
        {
            "url": "https://mattermost.example",
            "show_typing": False,
            "thread_follow_without_mention": True,
            "allow_from": ["alice", "bob"],
            "dm_policy": "allowlist",
            "group_policy": "allowlist",
            "deny_message": "Denied",
            "media_dir": "~/media",
        },
    ),
]


def reader():
    from qwenpaw.config.channel_env import read_channel_env

    return read_channel_env


@pytest.mark.parametrize("key,changes,expected", ENV_CASES)
def test_sdk_free_env_reader_preserves_literal_legacy_values(
    key, changes, expected
):
    supplied = {key.upper() + "_CHANNEL_ENABLED": "1", **changes}
    original = dict(supplied)
    config = reader()(key, MappingProxyType(supplied))
    assert isinstance(config, dict)
    assert {field: config[field] for field in expected} == expected
    assert supplied == original


def test_sdk_free_env_reader_uses_supplied_mapping_and_unknown_key_has_no_entry(
    monkeypatch,
):
    monkeypatch.setenv("MQTT_PORT", "9999")
    monkeypatch.setenv("MQTT_QOS", "1")
    config = reader()("mqtt", MappingProxyType({}))
    assert config["port"] == 1883 and config["qos"] == 2
    assert config["enabled"] is False and config["transport"] == "mqtt"
    assert reader()("channel-without-legacy-env-entry", {}) is None


def test_sdk_free_env_reader_returns_detached_allowlists():
    values = {"MATTERMOST_ALLOW_FROM": "alice, , bob"}
    first = reader()("mattermost", values)
    first["allow_from"].append("changed")
    assert reader()("mattermost", values)["allow_from"] == ["alice", "bob"]


@pytest.mark.parametrize(
    "key,env,expected",
    [
        (
            "feishu",
            {},
            {
                "enabled": False,
                "domain": "feishu",
                "allow_from": [],
                "streaming_enabled": False,
            },
        ),
        (
            "dingtalk",
            {},
            {
                "enabled": True,
                "message_type": "markdown",
                "cron_message_type": "markdown",
                "robot_code": "",
                "card_template_key": "content",
            },
        ),
        (
            "feishu",
            {
                "FEISHU_CHANNEL_ENABLED": "1",
                "FEISHU_ALLOW_FROM": " alice, , bob ",
                "FEISHU_DOMAIN": "lark",
                "FEISHU_APP_ID": " app ",
                "FEISHU_REQUIRE_MENTION": "1",
            },
            {
                "enabled": True,
                "allow_from": ["alice", "bob"],
                "domain": "lark",
                "app_id": " app ",
                "require_mention": True,
            },
        ),
        (
            "dingtalk",
            {
                "DINGTALK_CLIENT_ID": " client ",
                "DINGTALK_ROBOT_CODE": "",
                "DINGTALK_MESSAGE_TYPE": " TEXT ",
                "DINGTALK_CRON_MESSAGE_TYPE": "",
                "DINGTALK_CARD_TEMPLATE_KEY": "",
                "DINGTALK_ALLOW_FROM": " alice, , bob ",
                "DINGTALK_AT_SENDER_ON_REPLY": "1",
            },
            {
                "client_id": " client ",
                "robot_code": " client ",
                "message_type": "text",
                "cron_message_type": "markdown",
                "card_template_key": "content",
                "allow_from": ["alice", "bob"],
                "at_sender_on_reply": True,
            },
        ),
    ],
)
def test_feishu_and_dingtalk_literal_env_compatibility_is_sdk_free(
    key, env, expected
):
    result = reader()(key, MappingProxyType(env))
    assert {name: result[name] for name in expected} == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("key,changes,expected", ENV_CASES)
async def test_official_env_parser_preserves_legacy_values_without_sdk(
    tmp_path, monkeypatch, registry, key, changes, expected
):
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy

    # Clear this channel's inherited env so literal defaults are reproducible.
    import os

    prefix = key.upper() + "_"
    for name in tuple(os.environ):
        if name.startswith(prefix):
            monkeypatch.delenv(name)
    values = {prefix + "CHANNEL_ENABLED": "1", "QWENPAW_ENABLED_CHANNELS": key}
    if key == "mqtt":
        values.update(
            MQTT_HOST="mqtt.example",
            MQTT_SUBSCRIBE_TOPIC="in/+",
            MQTT_PUBLISH_TOPIC="out/{client_id}",
        )
    else:
        values.update(
            MATTERMOST_URL="https://mattermost.example",
            MATTERMOST_BOT_TOKEN="token",
        )
    for name, value in {**values, **changes}.items():
        monkeypatch.setenv(name, value)
    source = official_source(tmp_path, key)
    register_source(registry, source)
    manager = ChannelManager.from_env(unused_process)
    channel = await manager.get_channel(key)
    assert isinstance(channel, IsolatedChannelProxy)
    config = channel._launch_spec.config
    assert config["enabled"] is True
    expected_execution = dict(expected)
    if key == "mattermost" and expected_execution.get("media_dir") == "~/media":
        expected_execution["media_dir"] = str(Path.home() / "media")
    assert {field: config[field] for field in expected_execution} == expected_execution
    assert channel.channel_process.health_snapshot()["pid"] is None
