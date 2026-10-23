"""Frozen Discord business assertions through migrated public interfaces."""

import importlib
import sys
from types import SimpleNamespace as NS

import pytest

from extension_sample import ROOT


@pytest.fixture
def helpers(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/discord"))
    return importlib.import_module("qwenpaw_channel_discord.formatting")


@pytest.mark.parametrize(
    "content_type,filename,want",
    [
        ("image/png", "", "image"),
        ("video/mp4", "", "video"),
        ("audio/mpeg", "", "audio"),
        ("", "a.png", "image"),
        ("", "v.mp4", "video"),
        ("application/pdf", "x.png", "file"),
        ("application/pdf", "d.pdf", "file"),
        ("", "", "file"),
    ],
)
def test_original_attachment_classification(
    helpers, content_type, filename, want
):
    assert (
        helpers.classify_attachment(
            NS(content_type=content_type, filename=filename)
        )
        == want
    )




@pytest.mark.parametrize(
    "handle,want",
    [
        ("discord:ch:123456", {"channel_id": "123456"}),
        ("discord:dm:789012", {"user_id": "789012"}),
        ("", {}),
        ("invalid:format", {}),
        ("ch:123456", {}),
        ("discord:ch:123:extra", {"channel_id": "123"}),
    ],
)
def test_original_handle_routes(helpers, handle, want):
    assert helpers.route_from_handle(handle) == want




def test_original_newline_chunking_preserves_every_line(helpers):
    text = "\n".join(f"Line {i}" for i in range(100))
    chunks = helpers.chunk_text(text, max_len=500)
    assert "\n".join(chunks) == text
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_original_long_single_line_keeps_all_characters(helpers):
    chunks = helpers.chunk_text("a" * 5000)
    assert len(chunks) >= 2
    assert "".join(chunks) == "a" * 5000
    assert all(len(chunk) <= 2000 for chunk in chunks)




def test_original_environment_basic_and_policy_values_are_sdk_free():
    from qwenpaw.config.channel_env import read_channel_env

    values = read_channel_env(
        "discord",
        {
            "DISCORD_CHANNEL_ENABLED": "1",
            "DISCORD_BOT_TOKEN": "env_token_123",
            "DISCORD_HTTP_PROXY": "http://env.proxy:8080",
            "DISCORD_HTTP_PROXY_AUTH": "env_user:env_pass",
            "DISCORD_BOT_PREFIX": "[EnvBot] ",
            "DISCORD_DM_POLICY": "closed",
            "DISCORD_GROUP_POLICY": "allowlist",
            "DISCORD_ALLOW_FROM": "user1, user2, user3",
            "DISCORD_DENY_MESSAGE": "Custom deny message",
            "DISCORD_REQUIRE_MENTION": "1",
            "DISCORD_ACCEPT_BOT_MESSAGES": "1",
            "DISCORD_STREAMING_ENABLED": "1",
            "DISCORD_MEDIA_DIR": "legacy-media",
        },
    )
    assert values is not None
    assert values["enabled"] is True
    assert values["bot_token"] == "env_token_123"
    assert values["http_proxy"] == "http://env.proxy:8080"
    assert values["http_proxy_auth"] == "env_user:env_pass"
    assert values["bot_prefix"] == "[EnvBot] "
    assert values["dm_policy"] == "closed"
    assert values["group_policy"] == "allowlist"
    assert values["allow_from"] == ["user1", "user2", "user3"]
    assert values["deny_message"] == "Custom deny message"
    assert values["require_mention"] is True
    assert values["accept_bot_messages"] is True
    assert values["streaming_enabled"] is True
    assert values["media_dir"] == "legacy-media"
    assert "discord" not in sys.modules


def test_original_environment_defaults_empty_allowlist_and_literal_flags():
    from qwenpaw.config.channel_env import read_channel_env

    values = read_channel_env("discord", {"DISCORD_BOT_TOKEN": "token"})
    assert values["enabled"] is True
    assert values["dm_policy"] == "open"
    assert values["group_policy"] == "open"
    assert values["allow_from"] == []
    assert values["require_mention"] is False
    assert values["accept_bot_messages"] is False
    empty = read_channel_env("discord", {"DISCORD_ALLOW_FROM": ""})
    assert empty["allow_from"] == []
    literal = read_channel_env(
        "discord",
        {"DISCORD_CHANNEL_ENABLED": "true", "DISCORD_REQUIRE_MENTION": "True"},
    )
    assert literal["enabled"] is False and literal["require_mention"] is False


def test_original_config_values_and_none_defaults_remain_detached():
    from qwenpaw.config.channel_config_compat import normalize_channel_config

    config = {
        "enabled": True,
        "bot_token": "config_token_123",
        "http_proxy": "http://config.proxy:8080",
        "http_proxy_auth": "config_user:config_pass",
        "bot_prefix": "[ConfigBot] ",
        "dm_policy": "closed",
        "group_policy": "allowlist",
        "allow_from": ["admin1", "admin2"],
        "deny_message": "Config deny message",
        "require_mention": True,
        "accept_bot_messages": True,
    }
    values = normalize_channel_config("discord", config, dictionary=False)
    assert {key: values[key] for key in config} == config
    values["allow_from"].append("changed")
    assert config["allow_from"] == ["admin1", "admin2"]
    defaults = normalize_channel_config(
        "discord",
        {
            key: None
            for key in (
                "bot_token",
                "http_proxy",
                "http_proxy_auth",
                "bot_prefix",
                "dm_policy",
                "group_policy",
                "allow_from",
                "deny_message",
            )
        },
        dictionary=False,
    )
    assert defaults["bot_token"] == ""
    assert defaults["http_proxy"] == ""
    assert defaults["http_proxy_auth"] == ""
    assert defaults["bot_prefix"] == ""
    assert defaults["dm_policy"] == "open"
    assert defaults["group_policy"] == "open"
    assert defaults["allow_from"] == []
    assert defaults["deny_message"] == ""


@pytest.mark.parametrize(
    "sender,meta,want",
    [
        ("12345", {"is_dm": True, "user_id": "12345"}, "discord:dm:12345"),
        ("12345", {"is_dm": False, "channel_id": "67890"}, "discord:ch:67890"),
        ("99999", {"is_dm": False}, "discord:dm:99999"),
        ("user123", {}, "discord:dm:user123"),
        ("user123", None, "discord:dm:user123"),
        (
            "user123",
            {
                "is_dm": False,
                "channel_id": "chan123",
                "guild_id": "guild456",
                "message_id": "msg789",
                "extra_data": {"key": "value"},
            },
            "discord:ch:chan123",
        ),
    ],
)
def test_original_session_resolution(helpers, sender, meta, want):
    assert helpers.resolve_session_id(sender, meta) == want


def test_none_proxy_is_compatibility_wire_empty_but_typed_config_is_strict():
    from pydantic import ValidationError
    from qwenpaw.config.config import DiscordConfig
    from qwenpaw.config.channel_config_compat import normalize_channel_config

    assert (
        normalize_channel_config("discord", {"http_proxy": None})["http_proxy"]
        == ""
    )
    with pytest.raises(ValidationError):
        DiscordConfig(http_proxy=None)
    with pytest.raises(ValidationError):
        DiscordConfig(http_proxy=123)


def test_generic_proxy_keeps_original_request_identity_and_target_precedence():
    import json
    from qwenpaw.config.config import DiscordConfig
    from qwenpaw.channel_protocol.targets import decode_reply_target
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from g2_legacy_configuration_suite import proxy_for

    source = ROOT / "plugins/channel/discord"
    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    proxy = proxy_for(
        describe_channel(source, manifest), DiscordConfig(enabled=False)
    )
    request = proxy.build_agent_request_from_native(
        {
            "sender_id": "display",
            "user_id": "42",
            "session_id": "discord:dm:42",
            "content_parts": [{"type": "text", "text": "Hello"}],
            "meta": {"user_id": "42", "is_dm": True},
        }
    )
    assert request.user_id == "42"
    assert request.channel == "discord"
    assert request.channel_meta == {"user_id": "42", "is_dm": True}
    assert len(request.input) == 1
    assert request.input[0].content[0].text == "Hello"
    assert decode_reply_target(
        proxy.get_to_handle_from_request(
            NS(session_id="discord:ch:123", user_id="user456", channel_meta={})
        )
    ) == {"session_id": "discord:ch:123", "user_id": "user456"}
    assert decode_reply_target(
        proxy.get_to_handle_from_request(
            NS(session_id="", user_id="user789", channel_meta={})
        )
    ) == {"session_id": "", "user_id": "user789"}
    with pytest.raises(ProtocolValidationError):
        proxy.get_to_handle_from_request(
            NS(session_id="", user_id="", channel_meta={})
        )
    assert proxy.channel_process.health_snapshot()["pid"] is None
