"""Missing-code official configuration stays passive and editable."""

import asyncio
import importlib.abc
import json
import sys

import pytest

import official_g1_suite as core

registry = core.registry
saved_host = core.saved_host


@pytest.fixture
def passive_cli(saved_host, registry, monkeypatch):
    from qwenpaw.cli import channels_cmd as cli
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog
    from qwenpaw.config.config import Config
    from qwenpaw.config.utils import save_config
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

    config = Config.model_validate(
        {
            "channels": {
                "mqtt": {
                    "enabled": False,
                    "host": "old-broker",
                    "password": "old-secret",
                },
                "azure_bot": {
                    "enabled": False,
                    "app_id": "old-app",
                    "app_password": "old-secret",
                    "bot_prefix": "old ",
                },
            }
        }
    )
    save_config(config)
    attempts = []
    prefixes = tuple(
        "qwenpaw_channel_" + row["channel_key"] for row in OFFICIAL_CHANNELS
    )

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(prefixes) or fullname.split(".")[0] in {
                "aibot",
                "nio",
                "paho",
                "msal",
                "telegram",
                "discord",
                "slack_sdk",
                "lark_oapi",
                "dingtalk_stream",
            }:
                attempts.append(fullname)
                raise AssertionError("Passive CLI imported " + fullname)

    async def no_spawn(*args, **kwargs):
        attempts.append("subprocess")
        raise AssertionError("Passive CLI started worker")

    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    catalog = get_configurable_channel_catalog()
    assert (
        catalog["azure_bot"]["availability"]
        == catalog["mqtt"]["availability"]
        == "missing_code"
    )
    assert catalog["azure_bot"]["plugin_id"] == "azure-bot"
    yield cli, config, catalog, attempts
    assert attempts == []
    assert not (saved_host.parent / "plugins").exists()
    assert registry.get_channel_catalog() == {}


def test_missing_official_names_and_configurators_remain_available(
    passive_cli,
):
    cli, config, catalog, attempts = passive_cli
    names = cli._get_channel_names()
    configurators = cli.get_channel_configurators()
    for key in ("mqtt", "azure_bot", "wechat", "imessage"):
        assert key in names and key in configurators
        assert names[key] == catalog[key]["label"] or key in cli.CHANNEL_NAMES
    assert "azure-bot" not in names and "azure-bot" not in configurators


def test_missing_official_minimal_edit_preserves_saved_platform_fields(
    passive_cli, monkeypatch
):
    cli, config, catalog, attempts = passive_cli
    monkeypatch.setattr(cli, "prompt_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli.click, "prompt", lambda *args, **kwargs: "edited ")
    configurators = cli.get_channel_configurators()
    for key in ("mqtt", "azure_bot"):
        before = cli._get_channel_config(config, key)
        before = (
            before.model_dump(mode="json")
            if hasattr(before, "model_dump")
            else dict(before)
        )
        result = configurators[key][1](dict(before))
        assert result == {**before, "enabled": True, "bot_prefix": "edited "}
        assert (
            result["password" if key == "mqtt" else "app_password"]
            == "old-secret"
        )


def test_existing_special_wizards_and_registered_custom_configurator_win(
    passive_cli, registry
):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    cli, config, catalog, attempts = passive_cli
    calls = []

    class ExternalConfigPlugin(ConsoleChannel):
        channel = "external_config"
        display_name = "External configuration"

        @staticmethod
        def get_configurator():
            def configure(current):
                calls.append(current)
                current.external_field = "edited-by-plugin"
                return current

            return configure

    registration = registry.register_channel(
        "external-config",
        "external_config",
        ExternalConfigPlugin,
        label="External configuration",
    )
    try:
        configurators = cli.get_channel_configurators()
        assert configurators["imessage"][1] is cli.configure_imessage
        assert configurators["wechat"][1] is cli.configure_wechat
        result = configurators["external_config"][1](
            {"enabled": False, "external_field": "saved"}
        )
        assert (
            result == {"enabled": False, "external_field": "edited-by-plugin"}
            and len(calls) == 1
        )
    finally:
        assert registry.unregister_channel(
            "external_config", expected=registration
        )
        registry.unregister_plugin("external-config")
