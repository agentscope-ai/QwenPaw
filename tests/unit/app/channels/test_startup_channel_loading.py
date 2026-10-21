"""Configured startup must not import SDKs for disabled channels."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels import registry
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.config.config import ChannelConfig, Config, ConsoleConfig


class OptionalChannel(ConsoleChannel):
    channel = "optional"

    @classmethod
    def from_config(cls, process, config, **kwargs):
        return super().from_config(
            process=process,
            config=ConsoleConfig(enabled=config.enabled),
            **kwargs,
        )


@pytest.fixture
def imports(monkeypatch):
    seen = []
    real_import = registry.importlib.import_module
    monkeypatch.delenv("QWENPAW_ENABLED_CHANNELS", raising=False)
    monkeypatch.delenv("QWENPAW_DISABLED_CHANNELS", raising=False)
    monkeypatch.setattr(
        registry,
        "_BUILTIN_SPECS",
        {
            "console": (".console", "ConsoleChannel"),
            "optional": (".optional", "OptionalChannel"),
        },
    )
    monkeypatch.setattr(registry, "_BUILTIN_CHANNEL_CACHE", None)
    monkeypatch.setattr(registry, "_get_plugin_channels", lambda: {})

    def load(name, package=None):
        if package == registry.__package__ and name in {
            ".console",
            ".optional",
        }:
            seen.append(name)
            if name == ".optional":
                return SimpleNamespace(OptionalChannel=OptionalChannel)
        return real_import(name, package)

    monkeypatch.setattr(registry.importlib, "import_module", load)
    return seen


def create_manager(channels):
    return ChannelManager.from_config(
        process=AsyncMock(),
        config=Config(channels=channels),
    )


def test_disabled_sdk_is_not_imported_but_loads_when_enabled(imports):
    channels = ChannelConfig(optional={"enabled": False})
    first = create_manager(channels)
    assert [c.channel for c in first.channels] == ["console"]
    assert imports == [".console"]

    channels.optional["enabled"] = True
    second = create_manager(channels)
    assert {c.channel for c in second.channels} == {"console", "optional"}
    assert ".optional" in imports


def test_full_discovery_still_lists_disabled_channels(imports):
    create_manager(ChannelConfig(optional={"enabled": False}))
    assert set(registry.get_channel_registry()) == {"console", "optional"}


@pytest.mark.parametrize(
    ("env_name", "env_value", "expected"),
    [
        ("QWENPAW_ENABLED_CHANNELS", "optional", {"optional"}),
        ("QWENPAW_DISABLED_CHANNELS", "optional", {"console"}),
        ("QWENPAW_ENABLED_CHANNELS", "missing", {"console", "optional"}),
    ],
)
def test_explicit_environment_filter_semantics(
    imports,
    monkeypatch,
    env_name,
    env_value,
    expected,
):
    monkeypatch.setenv(env_name, env_value)
    manager = create_manager(ChannelConfig(optional={"enabled": True}))
    assert {c.channel for c in manager.channels} == expected


def test_configured_plugin_channel_remains_available(imports, monkeypatch):
    monkeypatch.setattr(
        registry,
        "_get_plugin_channels",
        lambda: {"optional": OptionalChannel},
    )
    monkeypatch.setattr(
        registry,
        "_BUILTIN_SPECS",
        {"console": (".console", "ConsoleChannel")},
    )
    manager = create_manager(ChannelConfig(optional={"enabled": True}))
    assert {c.channel for c in manager.channels} == {"console", "optional"}
