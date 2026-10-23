"""Original environment/config fields on real formal factories."""

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import describe_channel
from qwenpaw.plugins.official_channels import bundled_channel_source
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.__version__ import __version__
from wechat_w4_formal_support import wechat_host_import_guard

__all__ = ["wechat_host_import_guard"]
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def official_factory(tmp_path):
    with bundled_channel_source("wechat") as source:
        description = describe_channel(
            source,
            PluginManifest.from_dict(
                json.loads((source / "plugin.json").read_text())
            ),
        )

        def construct(values, *, config_source="config"):
            original = copy.deepcopy(values)
            channel = description.create_proxy(
                Runtime.run,
                values,
                python_executable=sys.executable,
                support_root=ROOT / "src",
                instance_id="wechat-config-oracle",
                generation=1,
                qwenpaw_version=__version__,
                workspace_dir=tmp_path / "workspace",
                config_source=config_source,
                display_config=ChannelDisplayConfig.from_config(
                    SimpleNamespace(**values)
                ),
            )
            assert values == original
            assert channel.channel_process.health_snapshot()["pid"] is None
            assert channel._launch_spec.plugin_id == "wechat"
            return channel

        yield construct


def test_from_config_handles_none_values(official_factory):
    channel = official_factory(
        {
            "enabled": False,
            "bot_token": None,
            "bot_prefix": None,
            "dm_policy": None,
            "group_policy": None,
        }
    )
    assert channel.enabled is False
    assert channel._launch_spec.config["bot_token"] == ""
    assert channel.bot_prefix == ""
    assert channel.dm_policy == "open"
    assert channel.group_policy == "open"


def test_from_config_uses_config_values(official_factory):
    channel = official_factory(
        {
            "enabled": True,
            "bot_token": "config_token_123",
            "bot_token_file": "/config/token.txt",
            "base_url": "https://config.api.com",
            "bot_prefix": "[ConfigBot] ",
            "media_dir": "/config/media",
            "dm_policy": "allowlist",
            "group_policy": "allowlist",
            "allow_from": ["user1", "user2"],
            "deny_message": "Config denied",
        }
    )
    assert channel.enabled is True
    assert channel._launch_spec.config["bot_token"] == "config_token_123"
    assert channel.bot_prefix == "[ConfigBot] "
    assert channel.dm_policy == "allowlist"
    assert channel.group_policy == "allowlist"
    assert channel._launch_spec.config["bot_token_file"] == "/config/token.txt"
    assert channel._launch_spec.config["media_dir"] == "/config/media"
    assert channel._launch_spec.config["base_url"] == "https://config.api.com"


def env_factory(factory, values):
    from qwenpaw.config.channel_env import read_channel_env

    return factory(read_channel_env("wechat", values), config_source="env")


def test_from_env_reads_basic_env_vars(official_factory):
    channel = env_factory(
        official_factory,
        {
            "WECHAT_CHANNEL_ENABLED": "1",
            "WECHAT_BOT_TOKEN": "env_token_123",
            "WECHAT_BOT_PREFIX": "[EnvBot] ",
            "WECHAT_BASE_URL": "https://env.api.com",
        },
    )
    assert channel.enabled is True
    assert channel._launch_spec.config["bot_token"] == "env_token_123"
    assert channel.bot_prefix == "[EnvBot] "
    assert channel._launch_spec.config["base_url"] == "https://env.api.com"


def test_from_env_reads_advanced_env_vars(official_factory):
    channel = env_factory(
        official_factory,
        {
            "WECHAT_BOT_TOKEN_FILE": "/env/token/file.txt",
            "WECHAT_MEDIA_DIR": "/env/media",
            "WECHAT_DM_POLICY": "allowlist",
            "WECHAT_GROUP_POLICY": "allowlist",
            "WECHAT_DENY_MESSAGE": "Env access denied",
        },
    )
    assert (
        Path(channel._launch_spec.config["bot_token_file"])
        == Path("/env/token/file.txt").expanduser()
    )
    assert (
        Path(channel._launch_spec.config["media_dir"])
        == Path("/env/media").expanduser()
    )
    assert channel.dm_policy == "allowlist"
    assert channel.group_policy == "allowlist"
    assert channel.deny_message == "Env access denied"


def test_from_env_allow_from_parsing(official_factory):
    channel = env_factory(
        official_factory, {"WECHAT_ALLOW_FROM": "user1,user2,user3"}
    )
    assert "user1" in channel.allow_from
    assert "user2" in channel.allow_from
    assert "user3" in channel.allow_from


def test_from_env_allow_from_empty(official_factory):
    channel = env_factory(official_factory, {"WECHAT_ALLOW_FROM": ""})
    assert channel.allow_from == set()


def test_from_env_defaults(official_factory):
    channel = env_factory(official_factory, {})
    assert channel.enabled is False
    assert channel.bot_prefix == ""
    assert channel.dm_policy == "open"
    assert channel.group_policy == "open"


def test_env_source_keeps_null_config_strict(official_factory):
    with pytest.raises(ValueError):
        official_factory(
            {"enabled": False, "bot_token": None}, config_source="env"
        )


def test_http_validation_keeps_null_credentials_strict():
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.plugins.channel_config import validate_channel_config

    with bundled_channel_source("wechat") as source:
        schema = SharedChannelDescriptor.load(
            source / "channel.json"
        ).config_schema
        values = {"enabled": False, "bot_token": None}
        with pytest.raises(ValueError):
            validate_channel_config(schema, values)
        assert values == {"enabled": False, "bot_token": None}
