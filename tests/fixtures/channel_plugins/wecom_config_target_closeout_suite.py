"""Old WeCom config/env and helper oracles on their current real owners."""

import sys
from pathlib import Path
import pytest
from qwenpaw.config.channel_env import read_channel_env
from wecom_contract_suite import official_wecom_proxy  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/wecom"))
from qwenpaw_channel_wecom.inbound import (  # noqa: E402
    resolve_session_id,
    parse_chatid_from_handle,
)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    from qwenpaw.config.config import Config

    monkeypatch.setattr("qwenpaw.app.channels.base.load_config", Config)


def test_from_env_reads_basic_env_vars(official_wecom_proxy):  # noqa: F811
    values = read_channel_env(
        "wecom",
        {
            "WECOM_CHANNEL_ENABLED": "1",
            "WECOM_BOT_ID": "env_bot_id",
            "WECOM_SECRET": "env_secret",
            "WECOM_BOT_PREFIX": "[EnvBot] ",
            "WECOM_MEDIA_DIR": "/env/media",
        },
    )
    channel = official_wecom_proxy(values, config_source="env")
    assert channel.enabled is True
    assert channel._launch_spec.config["bot_id"] == "env_bot_id"
    assert channel._launch_spec.config["secret"] == "env_secret"
    assert channel.bot_prefix == "[EnvBot] "
    assert channel._launch_spec.config["welcome_text"] == ""


def test_from_env_reads_policy_env_vars(
    official_wecom_proxy, no_platform_effects  # noqa: F811
):  # noqa: F811
    values = read_channel_env(
        "wecom",
        {
            "WECOM_CHANNEL_ENABLED": "1",
            "WECOM_BOT_ID": "bot_id",
            "WECOM_SECRET": "secret",
            "WECOM_DM_POLICY": "allowlist",
            "WECOM_GROUP_POLICY": "deny",
            "WECOM_ALLOW_FROM": "user1,user2,user3",
            "WECOM_DENY_MESSAGE": "Custom deny message",
            "WECOM_MAX_RECONNECT_ATTEMPTS": "10",
        },
    )
    assert values["dm_policy"] == "allowlist"
    assert values["group_policy"] == "deny"
    assert set(values["allow_from"]) == {"user1", "user2", "user3"}
    assert values["deny_message"] == "Custom deny message"
    assert values["max_reconnect_attempts"] == 10
    assert_group_policy_rejected(
        official_wecom_proxy, values, config_source="env"
    )
    assert no_platform_effects == []


def test_from_env_disabled_by_default(official_wecom_proxy):  # noqa: F811
    values = read_channel_env("wecom", {})
    channel = official_wecom_proxy(values, config_source="env")
    assert channel.enabled is False
    assert channel._launch_spec.config["bot_id"] == ""
    assert channel._launch_spec.config["secret"] == ""


def test_from_env_empty_allow_from(official_wecom_proxy):  # noqa: F811
    values = read_channel_env(
        "wecom",
        {
            "WECOM_CHANNEL_ENABLED": "1",
            "WECOM_BOT_ID": "bot_id",
            "WECOM_SECRET": "secret",
            "WECOM_ALLOW_FROM": "",
        },
    )
    channel = official_wecom_proxy(values, config_source="env")
    assert channel.allow_from == set()


def test_from_config_reads_basic_config(
    official_wecom_proxy, no_platform_effects  # noqa: F811
):  # noqa: F811
    values = {
        "enabled": True,
        "bot_id": "config_bot_id",
        "secret": "config_secret",
        "bot_prefix": "[Config] ",
        "media_dir": "/config/media",
        "welcome_text": "Config welcome",
        "dm_policy": "allowlist",
        "group_policy": "deny",
        "allow_from": ["user1"],
        "deny_message": "Go away",
        "max_reconnect_attempts": 3,
    }
    assert_group_policy_rejected(official_wecom_proxy, values)
    assert no_platform_effects == []


def test_from_config_handles_none_values(official_wecom_proxy):  # noqa: F811
    channel = official_wecom_proxy(
        {
            "enabled": False,
            "bot_id": None,
            "secret": None,
            "bot_prefix": None,
            "media_dir": None,
            "welcome_text": None,
            "dm_policy": None,
            "group_policy": None,
            "allow_from": None,
            "deny_message": None,
            "max_reconnect_attempts": None,
        }
    )
    assert channel.enabled is False
    assert channel._launch_spec.config["bot_id"] == ""
    assert channel._launch_spec.config["secret"] == ""
    assert channel.bot_prefix == ""
    assert channel._launch_spec.config["welcome_text"] == ""
    assert channel.dm_policy == "open"
    assert channel.group_policy == "open"
    assert channel.allow_from == set()
    assert channel.deny_message == ""
    assert channel._launch_spec.config["max_reconnect_attempts"] == -1


def test_resolve_session_id_single_chat():
    """resolve_session_id should return wecom:user for single chat."""
    session_id = resolve_session_id(
        sender_id="user_123", channel_meta={"wecom_chat_type": "single"}
    )
    assert session_id == "wecom:user_123"


def test_resolve_session_id_group_chat():
    """resolve_session_id returns wecom:group:chatid for group chat."""
    session_id = resolve_session_id(
        sender_id="user_123",
        channel_meta={"wecom_chat_type": "group", "wecom_chatid": "group_456"},
    )
    assert session_id == "wecom:group:group_456"


def test_resolve_session_id_fallback_to_chatid():
    """resolve_session_id falls back to chatid if no sender_id."""
    session_id = resolve_session_id(
        sender_id="", channel_meta={"wecom_chatid": "chat_789"}
    )
    assert session_id == "wecom:chat_789"


def test_resolve_session_id_unknown():
    """resolve_session_id returns wecom:unknown for empty identifiers."""
    session_id = resolve_session_id(sender_id="", channel_meta={})
    assert session_id == "wecom:unknown"


def test_parse_chatid_from_handle_single():
    """_parse_chatid_from_handle extracts userid from single chat."""
    chatid = parse_chatid_from_handle("wecom:user_123")
    assert chatid == "user_123"


def test_parse_chatid_from_handle_group():
    """_parse_chatid_from_handle extracts chatid from group."""
    chatid = parse_chatid_from_handle("wecom:group:group_123")
    assert chatid == "group_123"


def test_parse_chatid_from_handle_plain():
    """_parse_chatid_from_handle returns plain string as-is."""
    chatid = parse_chatid_from_handle("plain_id")
    assert chatid == "plain_id"


def test_wecom_parse_chatid_from_handle() -> None:
    """Chat id extracted from wecom handle prefixes."""
    parse = parse_chatid_from_handle
    assert parse("wecom:group:C1") == "C1"
    assert parse("wecom:U1") == "U1"
    assert parse("plain") == "plain"


@pytest.fixture
def no_platform_effects(monkeypatch):
    import asyncio
    import importlib.abc
    from qwenpaw.plugins.execution.process import PluginProcess

    effects = []

    class RejectSDK(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "aibot" or fullname.startswith("aibot."):
                effects.append(fullname)
                raise AssertionError("SDK imported by passive factory")

    async def reject_start(*args, **kwargs):
        effects.append("process.start")
        raise AssertionError("worker started by passive factory")

    assert "aibot" not in sys.modules
    monkeypatch.setattr(sys, "meta_path", [RejectSDK(), *sys.meta_path])
    monkeypatch.setattr(PluginProcess, "start", reject_start)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", reject_start)
    yield effects
    assert effects == []


def assert_group_policy_rejected(construct, values, **kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as caught:
        construct(values, **kwargs)
    assert [
        (e["loc"], e["type"], e["input"]) for e in caught.value.errors()
    ] == [(("group_policy",), "literal_error", "deny")]


@pytest.mark.parametrize("group_policy", ["open", "allowlist"])
def test_valid_config_retains_all_original_fields(
    official_wecom_proxy, no_platform_effects, group_policy  # noqa: F811
):  # noqa: F811
    channel = official_wecom_proxy(
        {
            "enabled": True,
            "bot_id": "config_bot_id",
            "secret": "config_secret",
            "bot_prefix": "[Config] ",
            "media_dir": "/config/media",
            "welcome_text": "Config welcome",
            "dm_policy": "allowlist",
            "group_policy": group_policy,
            "allow_from": ["user1"],
            "deny_message": "Go away",
            "max_reconnect_attempts": 3,
        }
    )
    assert channel.enabled is True
    assert channel._launch_spec.config["bot_id"] == "config_bot_id"
    assert channel._launch_spec.config["secret"] == "config_secret"
    assert channel.bot_prefix == "[Config] "
    assert channel._launch_spec.config["welcome_text"] == "Config welcome"
    assert channel.dm_policy == "allowlist"
    assert channel.group_policy == group_policy
    assert channel.allow_from == {"user1"}
    assert channel.deny_message == "Go away"
    assert channel._launch_spec.config["max_reconnect_attempts"] == 3
    assert no_platform_effects == []
