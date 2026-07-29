# -*- coding: utf-8 -*-
"""Tests for renaming custom providers via the config endpoint."""

from types import SimpleNamespace

from qwenpaw.app.routers.providers import (
    ProviderConfigRequest,
    configure_provider,
)


class FakeManager:
    """Records update_provider calls for assertion."""

    def __init__(self, is_custom: bool) -> None:
        self._provider = SimpleNamespace(is_custom=is_custom)
        self.last_config: dict | None = None

    def get_provider(self, _provider_id: str):
        return self._provider

    def update_provider(self, _provider_id: str, config: dict) -> bool:
        self.last_config = config
        return True

    async def get_provider_info(self, _provider_id: str):
        return SimpleNamespace(id="fake")


async def test_configure_custom_provider_applies_stripped_name():
    manager = FakeManager(is_custom=True)
    body = ProviderConfigRequest(name="  New Name  ")

    await configure_provider(
        manager=manager,
        provider_id="my-custom",
        body=body,
    )

    assert manager.last_config is not None
    assert manager.last_config["name"] == "New Name"


async def test_configure_builtin_provider_ignores_name():
    manager = FakeManager(is_custom=False)
    body = ProviderConfigRequest(name="Hacked Name")

    await configure_provider(
        manager=manager,
        provider_id="openai",
        body=body,
    )

    assert manager.last_config is not None
    assert "name" not in manager.last_config


async def test_configure_provider_ignores_blank_name():
    manager = FakeManager(is_custom=True)
    body = ProviderConfigRequest(name="   ")

    await configure_provider(
        manager=manager,
        provider_id="my-custom",
        body=body,
    )

    assert manager.last_config is not None
    assert "name" not in manager.last_config
