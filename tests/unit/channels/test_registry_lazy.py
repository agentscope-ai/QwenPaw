# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qwenpaw.app.channels.base import BaseChannel


class _FakeChannel(BaseChannel):
    channel = "console"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        return None


class _HeavyFakeChannel(_FakeChannel):
    channel = "heavy"


def test_get_channel_registry_loads_only_requested_builtin(monkeypatch):
    from qwenpaw.app.channels import registry

    imported_modules: list[str] = []
    modules = {
        "console_mod": SimpleNamespace(ConsoleChannel=_FakeChannel),
        "heavy_mod": SimpleNamespace(HeavyChannel=_HeavyFakeChannel),
    }

    def import_module(name: str, package: str | None = None):
        imported_modules.append(name)
        return modules[name]

    monkeypatch.setattr(
        registry,
        "_BUILTIN_SPECS",
        {
            "console": ("console_mod", "ConsoleChannel"),
            "heavy": ("heavy_mod", "HeavyChannel"),
        },
    )
    monkeypatch.setattr(registry, "_REQUIRED_CHANNEL_KEYS", frozenset({"console"}))
    monkeypatch.setattr(registry.importlib, "import_module", import_module)
    monkeypatch.setattr(registry, "_discover_custom_channels", lambda keys=None: {})
    registry.clear_builtin_channel_cache()

    result = registry.get_channel_registry(["console"])

    assert result == {"console": _FakeChannel}
    assert imported_modules == ["console_mod"]


def test_channel_manager_from_config_requests_enabled_channels(monkeypatch):
    from qwenpaw.app.channels import manager

    requested_available_keys: list[tuple[str, ...]] = []
    requested_registry_keys: list[tuple[str, ...]] = []

    class DummyChannel:
        channel = "console"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def get_available_channels(candidate_keys=None):
        keys = tuple(candidate_keys or ())
        requested_available_keys.append(keys)
        return keys

    def get_channel_registry(keys=None):
        requested_registry_keys.append(tuple(keys or ()))
        return {
            "console": DummyChannel,
            "feishu": DummyChannel,
        }

    config = SimpleNamespace(
        show_tool_details=True,
        channels=SimpleNamespace(
            console=SimpleNamespace(enabled=True),
            feishu=SimpleNamespace(enabled=False),
        ),
    )

    monkeypatch.setattr(manager, "get_available_channels", get_available_channels)
    monkeypatch.setattr(manager, "get_channel_registry", get_channel_registry)

    channel_manager = manager.ChannelManager.from_config(
        config,
        process=lambda request: None,
    )

    assert requested_available_keys == [("console",)]
    assert requested_registry_keys == [("console",)]
    assert [channel.channel for channel in channel_manager.channels] == ["console"]
