"""Legacy configuration and inherited host contracts after Slack ownership
moves."""

import json
import sys
from types import SimpleNamespace as NS

import pytest

from extension_sample import ROOT
from g2_legacy_configuration_suite import proxy_for
from slack_suite import forbid_host_sdk

sys.path.insert(0, str(ROOT))


def static_proxy(config=None, **options):
    from qwenpaw.config.config import SlackConfig
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = ROOT / "plugins/channel/slack"
    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    return proxy_for(
        describe_channel(source, manifest), config or SlackConfig(), **options
    )




def test_original_init_and_contract_credential_projection():
    from qwenpaw.config.config import SlackConfig

    proxy = static_proxy(
        SlackConfig(
            enabled=True,
            bot_token="xoxb-test-bot-token",
            app_token="xapp-test-app-token",
            bot_prefix="[SlackBot] ",
            streaming_enabled=True,
            require_mention=True,
        )
    )
    config = proxy._launch_spec.config
    assert proxy.enabled is True
    assert config["bot_token"] == "xoxb-test-bot-token"
    assert config["app_token"] == "xapp-test-app-token"
    assert proxy.bot_prefix == "[SlackBot] "
    assert config["streaming_enabled"] is True
    assert config["require_mention"] is True
    credentials = static_proxy(
        SlackConfig(bot_token="xoxb-test-token", app_token="xapp-test-token")
    )._launch_spec.config
    assert credentials["bot_token"] == "xoxb-test-token"
    assert credentials["app_token"] == "xapp-test-token"


def test_original_environment_names_flags_tokens_prefix_proxy_and_allowlist():
    from qwenpaw.config.channel_env import read_channel_env

    values = read_channel_env(
        "slack",
        {
            "SLACK_CHANNEL_ENABLED": "1",
            "SLACK_BOT_TOKEN": "xoxb-env-token",
            "SLACK_APP_TOKEN": "xapp-env-token",
            "SLACK_BOT_PREFIX": "[Env] ",
            "SLACK_PROXY": "http://proxy:8080",
            "SLACK_STREAMING_ENABLED": "1",
            "SLACK_REQUIRE_MENTION": "0",
            "SLACK_ALLOW_FROM": "user1, user2",
        },
    )
    assert values["enabled"] is True
    assert values["bot_token"] == "xoxb-env-token"
    assert values["app_token"] == "xapp-env-token"
    assert values["bot_prefix"] == "[Env] "
    assert values["proxy"] == "http://proxy:8080"
    assert values["streaming_enabled"] is True
    assert values["require_mention"] is False
    assert "user1" in values["allow_from"]
    assert "user2" in values["allow_from"]


def test_environment_defaults_literal_flags_and_untrimmed_tokens():
    from qwenpaw.config.channel_env import read_channel_env

    defaults = read_channel_env("slack", {})
    assert defaults["enabled"] is False
    assert defaults["require_mention"] is True
    assert defaults["streaming_enabled"] is False
    assert defaults["allow_from"] == []
    values = read_channel_env(
        "slack",
        {
            "SLACK_BOT_TOKEN": " token ",
            "SLACK_APP_TOKEN": " app ",
            "SLACK_BOT_PREFIX": " prefix ",
            "SLACK_CHANNEL_ENABLED": "true",
            "SLACK_STREAMING_ENABLED": "True",
            "SLACK_ALLOW_FROM": " a, ,b ",
        },
    )
    assert values["bot_token"] == " token "
    assert values["app_token"] == " app "
    assert values["bot_prefix"] == " prefix "
    assert values["enabled"] is False
    assert values["streaming_enabled"] is False
    assert values["allow_from"] == ["a", "b"]


def test_original_config_policy_display_and_detach():
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig
    from qwenpaw.config.config import SlackConfig
    from qwenpaw.config.channel_config_compat import normalize_channel_config

    config = SlackConfig(
        enabled=True,
        bot_token="xoxb-config",
        app_token="xapp-config",
        bot_prefix="[Config] ",
        proxy="http://config-proxy",
        streaming_enabled=False,
        require_mention=False,
        dm_policy="allowlist",
        group_policy="allowlist",
        allow_from=["one"],
        dm_disabled=True,
        group_disabled=True,
        access_control_dm=True,
        access_control_group=True,
        show_tool_calls=False,
        show_tool_results=False,
        show_thinking=False,
    )
    proxy = static_proxy(
        config,
        display_config=ChannelDisplayConfig(
            show_tool_details=False,
            show_tool_calls=False,
            show_tool_results=False,
            show_thinking=False,
        ),
    )
    assert proxy.enabled is True
    assert proxy._launch_spec.config["bot_token"] == "xoxb-config"
    assert proxy._launch_spec.config["app_token"] == "xapp-config"
    assert proxy.bot_prefix == "[Config] "
    assert proxy._launch_spec.config["proxy"] == "http://config-proxy"
    assert proxy._launch_spec.config["streaming_enabled"] is False
    assert proxy._launch_spec.config["require_mention"] is False
    assert proxy.dm_policy == "allowlist"
    assert proxy.group_policy == "allowlist"
    assert (
        proxy._launch_spec.config["dm_disabled"] is True
        and proxy._launch_spec.config["group_disabled"] is True
    )
    assert (
        proxy.access_control_dm is True and proxy.access_control_group is True
    )
    assert proxy._display_config.show_tool_calls is False
    assert proxy._display_config.show_tool_details is False
    assert proxy._display_config.show_tool_results is False
    assert proxy._display_config.show_thinking is False
    detached = normalize_channel_config("slack", config.model_dump())
    detached["allow_from"].append("two")
    assert config.allow_from == ["one"]
    assert proxy.channel_process.health_snapshot()["pid"] is None


def test_legacy_none_falsey_values_normalize_but_http_model_stays_strict():
    from pydantic import ValidationError
    from qwenpaw.config.config import SlackConfig
    from qwenpaw.config.channel_config_compat import normalize_channel_config

    values = normalize_channel_config(
        "slack",
        {
            "bot_token": None,
            "app_token": None,
            "bot_prefix": None,
            "allow_from": None,
            "dm_policy": None,
            "group_policy": None,
            "access_control_dm": "yes",
        },
    )
    assert (
        values["bot_token"]
        == values["app_token"]
        == values["bot_prefix"]
        == ""
    )
    assert values["allow_from"] == []
    assert values["dm_policy"] == values["group_policy"] == "open"
    assert values["access_control_dm"] is True
    with pytest.raises(ValidationError):
        SlackConfig(proxy=123)


def test_original_native_request_identity_and_opaque_target_precedence():
    from qwenpaw.channel_protocol.targets import decode_reply_target

    proxy = static_proxy()
    request = proxy.build_agent_request_from_native(
        {
            "channel_id": "slack",
            "sender_id": "U123",
            "user_id": "U123",
            "session_id": "slack:thread:C123:123.456",
            "content_parts": [{"type": "text", "text": "Hi"}],
            "meta": {"slack_channel_id": "C123", "slack_thread_ts": "123.456"},
        }
    )
    assert request.user_id == "U123"
    assert request.channel == "slack"
    assert request.session_id == "slack:thread:C123:123.456"
    assert len(request.input) == 1
    assert decode_reply_target(proxy.get_to_handle_from_request(request)) == {
        "session_id": "slack:thread:C123:123.456",
        "user_id": "U123",
    }
    for session in ("slack:ch:C123", ""):
        assert decode_reply_target(
            proxy.to_handle_from_target(user_id="U123", session_id=session)
        ) == {"session_id": session, "user_id": "U123"}
    assert proxy.channel == "slack"


@pytest.mark.asyncio
async def test_disabled_static_proxy_direct_and_parts_have_no_worker():
    proxy = static_proxy()
    assert proxy.enabled is False
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    before = dict(proxy._launch_spec.config)
    before_health = proxy.channel_process.health_snapshot()
    for entry in (
        proxy.send("C123", "Hello"),
        proxy.send_content_parts("C123", [{"type": "text", "text": "Hello"}]),
    ):
        with pytest.raises(ChannelDeliveryError) as caught:
            await entry
        assert caught.value.state == "failed"
        assert caught.value.reason_code == "CHANNEL_DISABLED"
    assert dict(proxy._launch_spec.config) == before
    assert proxy.channel_process.health_snapshot() == before_health
    assert proxy.channel_process.health_snapshot()["pid"] is None
