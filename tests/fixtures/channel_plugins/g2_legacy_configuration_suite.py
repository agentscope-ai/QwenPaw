"""Original from_config literals through the real static proxy factory."""

import sys
from types import SimpleNamespace

import pytest

from extension_admission_suite import registry
from extension_sample import ROOT
from g2_environment_suite import register_source, unused_process
from g2_official_process_suite import official_source, forbid_host_sdk_import


def proxy_for(description, config, **options):
    return description.create_proxy(
        unused_process,
        config,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="legacy-config",
        generation=1,
        qwenpaw_version="2.2.2b4",
        **options,
    )


def test_compatibility_reader_is_detached_and_keeps_invalid_numeric_fallbacks():
    from qwenpaw.config.channel_config_compat import normalize_channel_config

    values = {
        "port": "invalid",
        "qos": "invalid",
        "allow_from": ["one"],
        "custom": {"items": [1]},
    }
    result = normalize_channel_config("mqtt", values)
    assert result["port"] == 1883 and result["qos"] == 0
    result["allow_from"].append("changed")
    result["custom"]["items"].append(2)
    assert values == {
        "port": "invalid",
        "qos": "invalid",
        "allow_from": ["one"],
        "custom": {"items": [1]},
    }


CONFIG_CASES = [
    (
        "mqtt",
        {
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
        },
        {
            "enabled": True,
            "host": "dict.mqtt.local",
            "port": 1883,
            "username": "dict_user",
            "clean_session": False,
            "qos": 0,
            "transport": "websockets",
        },
    ),
    (
        "mqtt",
        {
            "enabled": True,
            "host": "  spaced.host  ",
            "subscribe_topic": "  spaced/in  ",
            "publish_topic": "  spaced/out  ",
        },
        {
            "host": "spaced.host",
            "subscribe_topic": "spaced/in",
            "publish_topic": "spaced/out",
        },
    ),
    (
        "mattermost",
        {
            "enabled": True,
            "url": " https://config.mm.com/// ",
            "bot_token": " config_token_123 ",
            "bot_prefix": "[ConfigBot] ",
            "dm_policy": "allowlist",
            "group_policy": "allowlist",
        },
        {
            "enabled": True,
            "url": "https://config.mm.com",
            "bot_token": "config_token_123",
            "bot_prefix": "[ConfigBot]",
            "dm_policy": "allowlist",
            "group_policy": "allowlist",
        },
    ),
    (
        "mattermost",
        {
            "enabled": None,
            "url": None,
            "bot_token": None,
            "bot_prefix": None,
            "dm_policy": None,
            "group_policy": None,
        },
        {
            "enabled": False,
            "url": "",
            "bot_token": "",
            "bot_prefix": "",
            "dm_policy": "open",
            "group_policy": "open",
        },
    ),
    (
        "mattermost",
        {"enabled": True, "url": "", "bot_token": "token123"},
        {"enabled": False, "url": "", "bot_token": "token123"},
    ),
    (
        "mattermost",
        {"enabled": True, "url": "https://mm.example.com", "bot_token": ""},
        {"enabled": False, "url": "https://mm.example.com", "bot_token": ""},
    ),
]


@pytest.mark.parametrize("key,config,expected", CONFIG_CASES)
def test_original_dictionary_config_compatibility_at_public_factory(
    tmp_path, registry, key, config, expected
):
    source = official_source(tmp_path, key)
    description = register_source(registry, source)
    channel = description.create_proxy(
        unused_process,
        config,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="legacy-config-" + key,
        generation=1,
        qwenpaw_version="2.2.2b4",
    )
    actual = channel._launch_spec.config
    assert {field: actual[field] for field in expected} == expected
    assert channel.channel_process.health_snapshot()["pid"] is None


@pytest.mark.parametrize(
    "key,model_name,values,expected",
    [
        (
            "mqtt",
            "MQTTConfig",
            {
                "enabled": True,
                "host": "obj.mqtt.local",
                "port": 8883,
                "username": "obj_user",
                "password": "obj_pass",
                "subscribe_topic": "obj/in",
                "publish_topic": "obj/out",
                "bot_prefix": "[OBJ] ",
                "clean_session": True,
                "qos": 2,
                "transport": "tcp",
                "tls_enabled": False,
            },
            {"host": "obj.mqtt.local", "port": 8883},
        ),
        (
            "mattermost",
            "MattermostConfig",
            {
                "enabled": True,
                "url": "https://config.mm.com",
                "bot_token": "config_token_123",
                "bot_prefix": "[ConfigBot] ",
                "media_dir": "/config/media",
                "show_typing": False,
                "thread_follow_without_mention": True,
                "dm_policy": "allowlist",
                "group_policy": "allowlist",
                "allow_from": ["user1", "user2"],
                "deny_message": "Config denied",
            },
            {
                "enabled": True,
                "url": "https://config.mm.com",
                "bot_token": "config_token_123",
                "bot_prefix": "[ConfigBot]",
                "dm_policy": "allowlist",
                "group_policy": "allowlist",
            },
        ),
    ],
)
def test_original_config_object_values_use_actual_light_model(
    tmp_path, registry, key, model_name, values, expected
):
    from qwenpaw.config import config as models

    description = register_source(registry, official_source(tmp_path, key))
    channel = proxy_for(description, getattr(models, model_name)(**values))
    assert {
        field: channel._launch_spec.config[field] for field in expected
    } == expected
    assert channel.channel_process.health_snapshot()["pid"] is None


def test_original_mattermost_display_and_acl_policy_contracts(
    tmp_path, registry
):
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig

    description = register_source(
        registry, official_source(tmp_path, "mattermost")
    )
    display = ChannelDisplayConfig(
        show_thinking=False, show_tool_calls=False, show_tool_results=False
    )
    channel = proxy_for(
        description,
        {
            "enabled": False,
            "url": "https://mm.example.com",
            "bot_token": "token",
            "allow_from": ["user1", "user2"],
            "deny_message": "Access denied",
        },
        display_config=display,
    )
    assert channel.enabled is False
    assert channel._display_config.show_tool_details is True
    assert (
        not channel._display_config.show_thinking
        and not channel._display_config.show_tool_calls
        and not channel._display_config.show_tool_results
    )
    assert channel.allow_from == {"user1", "user2"}
    assert channel.deny_message == "Access denied"
    assert channel.access_control_enabled is False
    channel.access_control_dm = True
    assert channel.access_control_enabled is True
    channel.access_control_dm = False
    channel.access_control_group = True
    assert channel.access_control_enabled is True


@pytest.mark.asyncio
async def test_manager_keeps_numeric_string_legacy_mqtt_config(
    tmp_path, registry
):
    from qwenpaw.app.channels.manager import ChannelManager

    source = official_source(tmp_path, "mqtt")
    register_source(registry, source)
    key, config, expected = CONFIG_CASES[0]
    manager = ChannelManager.from_config(
        unused_process,
        SimpleNamespace(channels={key: config}),
        workspace_dir=tmp_path / "workspace",
    )
    channel = await manager.get_channel(key)
    assert (
        channel is not None
    ), "Descriptor factory dropped the legacy dictionary config"
    assert {
        field: channel._launch_spec.config[field] for field in expected
    } == expected
    assert channel.channel_process.health_snapshot()["pid"] is None
