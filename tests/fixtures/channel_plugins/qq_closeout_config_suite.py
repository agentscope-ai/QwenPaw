"""Original QQ factory/env business inputs on real official unstarted Proxy."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.__version__ import __version__
from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.config.channel_env import read_channel_env
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import describe_channel
from qwenpaw.plugins.official_channels import bundled_channel_source
from qwenpaw.runtime.runtime import Runtime
from qq_closeout_formal_support import qq_host_import_guard

__all__ = ["qq_host_import_guard"]
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def official_factory(tmp_path):
    with bundled_channel_source("qq") as source:
        description = describe_channel(
            source,
            PluginManifest.from_dict(
                json.loads((source / "plugin.json").read_text())
            ),
        )

        def construct(values, *, config_source="config"):
            before = deepcopy(values)
            channel = description.create_proxy(
                Runtime.run,
                values,
                python_executable=sys.executable,
                support_root=ROOT / "src",
                instance_id="qq-factory-oracle",
                generation=1,
                qwenpaw_version=__version__,
                workspace_dir=tmp_path / "workspace",
                config_source=config_source,
                display_config=ChannelDisplayConfig.from_config(
                    SimpleNamespace(**values)
                ),
            )
            assert values == before
            assert channel.channel_process.health_snapshot()["pid"] is None
            assert channel._launch_spec.plugin_id == "qq"
            return channel

        yield construct


def test_from_env_reads_basic_env_vars(official_factory):
    values = read_channel_env(
        "qq",
        {
            "QQ_CHANNEL_ENABLED": "1",
            "QQ_APP_ID": "env_app_id",
            "QQ_CLIENT_SECRET": "env_secret",
            "QQ_BOT_PREFIX": "[EnvBot] ",
            "QQ_MARKDOWN_ENABLED": "false",
        },
    )
    channel = official_factory(values, config_source="env")
    assert channel.enabled is True
    assert channel._launch_spec.config["app_id"] == "env_app_id"
    assert channel._launch_spec.config["client_secret"] == "env_secret"
    assert channel.bot_prefix == "[EnvBot] "
    assert channel._launch_spec.config["markdown_enabled"] is False


def test_from_env_defaults(official_factory):
    values = read_channel_env("qq", {"QQ_APP_ID": "", "QQ_CLIENT_SECRET": ""})
    channel = official_factory(values, config_source="env")
    assert hasattr(channel, "bot_prefix")
    assert channel.bot_prefix == ""
    assert "markdown_enabled" in channel._launch_spec.config
    assert channel._launch_spec.config["markdown_enabled"] is True


def test_from_config_uses_config_values(official_factory):
    channel = official_factory(
        {
            "enabled": True,
            "app_id": "config_app_id",
            "client_secret": "config_secret",
            "bot_prefix": "[ConfigBot] ",
            "markdown_enabled": False,
            "media_dir": "/config/media",
            "max_reconnect_attempts": 20,
        }
    )
    assert channel.enabled is True
    assert channel._launch_spec.config["app_id"] == "config_app_id"
    assert channel.bot_prefix == "[ConfigBot] "
    assert channel._launch_spec.config["markdown_enabled"] is False
    assert channel._launch_spec.config["max_reconnect_attempts"] == 20


def test_from_config_handles_none_values(official_factory):
    # Original name retained: original fixture contains no literal None.
    channel = official_factory(
        {
            "enabled": False,
            "app_id": "",
            "client_secret": "",
            "bot_prefix": "",
            "markdown_enabled": True,
        }
    )
    assert channel.enabled is False
    assert channel._launch_spec.config["app_id"] == ""
    assert channel._launch_spec.config["client_secret"] == ""
    assert channel.bot_prefix == ""
    assert channel._launch_spec.config["markdown_enabled"] is not False
