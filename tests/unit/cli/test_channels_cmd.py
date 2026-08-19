# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Tests for interactive plugin channel configuration."""

import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from qwenpaw.cli import channels_cmd
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture()
def fresh_plugin_registry():
    """Provide an isolated plugin registry for CLI loading tests."""
    old_instance = PluginRegistry._instance
    old_loaded = channels_cmd._CLI_CHANNEL_PLUGINS_LOADED
    PluginRegistry._instance = None
    channels_cmd._CLI_CHANNEL_PLUGINS_LOADED = False
    registry = PluginRegistry()
    try:
        yield registry
    finally:
        sys.modules.pop("plugin_interactive_channel", None)
        PluginRegistry._instance = old_instance
        channels_cmd._CLI_CHANNEL_PLUGINS_LOADED = old_loaded


def _write_channel_plugin(plugin_root: Path) -> None:
    """Write a plugin with custom and fallback channel configurators."""
    plugin_dir = plugin_root / "interactive-channel"
    plugin_dir.mkdir()
    manifest = {
        "id": "interactive-channel",
        "name": "Interactive Channel",
        "version": "1.0.0",
        "type": "channel",
        "entry": {"backend": "plugin.py"},
        "qwenpaw_version": {"min": "0.1.0", "max": "99.0.0"},
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """
from fastapi import APIRouter

from qwenpaw.app.channels.base import BaseChannel


class InteractiveChannel(BaseChannel):
    channel = "interactive_channel"
    display_name = "Interactive Channel"

    @classmethod
    def get_configurator(cls):
        def configure(current):
            current.enabled = True
            current.binding_method = "qrcode"
            return current

        return configure


class FallbackChannel(BaseChannel):
    channel = "fallback_channel"
    display_name = "Fallback Channel"


class TestPlugin:
    def register(self, api):
        api.register_channel(channel_class=InteractiveChannel)
        api.register_channel(channel_class=FallbackChannel)
        router = APIRouter()
        api.register_http_router(router, prefix="/interactive-channel")


plugin = TestPlugin()
""".lstrip(),
        encoding="utf-8",
    )


@pytest.fixture()
def loaded_channel_plugin(tmp_path, fresh_plugin_registry):
    """Load the test channel plugin into an isolated registry."""
    _write_channel_plugin(tmp_path)

    with (
        patch.object(channels_cmd, "get_plugins_dir", return_value=tmp_path),
        patch.object(channels_cmd, "load_config") as load_config,
    ):
        load_config.return_value.plugins = {}
        channels_cmd._load_channel_plugins_for_cli()

    return fresh_plugin_registry


def test_cli_loads_plugin_channel_custom_configurator(
    loaded_channel_plugin,
):
    """Installed plugin channels expose their custom CLI configurator."""
    configurators = channels_cmd.get_channel_configurators()
    _, configure = configurators["interactive_channel"]
    updated = configure({"enabled": False})

    assert updated == {
        "enabled": True,
        "binding_method": "qrcode",
    }
    assert loaded_channel_plugin.get_channel_registration(
        "interactive_channel",
    )


def test_plugin_channel_without_custom_configurator_uses_fallback(
    loaded_channel_plugin,
):
    """Plugin channels without the hook keep the basic CLI prompts."""
    configurators = channels_cmd.get_channel_configurators()
    _, configure = configurators["fallback_channel"]
    with (
        patch.object(channels_cmd, "prompt_confirm", return_value=True),
        patch.object(channels_cmd.click, "prompt", return_value="[BOT]"),
    ):
        updated = configure({"enabled": False, "bot_prefix": ""})

    assert updated == {"enabled": True, "bot_prefix": "[BOT]"}
    assert loaded_channel_plugin.get_channel_registration(
        "fallback_channel",
    )


def test_interactive_config_loads_plugins_before_building_menu():
    """The interactive flow loads plugins before reading configurators."""
    calls = []

    def load_plugins():
        calls.append("load")

    def get_configurators():
        calls.append("configurators")
        return {}

    with (
        patch.object(
            channels_cmd,
            "_load_channel_plugins_for_cli",
            side_effect=load_plugins,
        ),
        patch.object(
            channels_cmd,
            "get_channel_configurators",
            side_effect=get_configurators,
        ),
        patch.object(channels_cmd, "get_channel_registry", return_value={}),
        patch.object(channels_cmd, "prompt_select", return_value="exit"),
    ):
        channels_cmd.configure_channels_interactive(channels_cmd.Config())

    assert calls == ["load", "configurators"]
