# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for OpenRouter provider resource management."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import qwenpaw.providers.openrouter_provider as openrouter_provider_module
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider_manager import ProviderManager


def _make_provider() -> OpenRouterProvider:
    return OpenRouterProvider(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.example/v1",
        api_key="sk-or-test",
    )


async def test_check_connection_closes_client(monkeypatch) -> None:
    provider = _make_provider()
    close = AsyncMock()
    models = SimpleNamespace(
        list=AsyncMock(return_value=SimpleNamespace(data=[])),
    )
    client = SimpleNamespace(models=models, close=close)
    monkeypatch.setattr(provider, "_client", lambda timeout=30: client)

    result = await provider.check_connection(timeout=2)

    assert result == (True, "")
    close.assert_awaited_once()


async def test_fetch_models_closes_client_on_api_error(monkeypatch) -> None:
    provider = _make_provider()
    close = AsyncMock()
    models = SimpleNamespace(list=AsyncMock(side_effect=RuntimeError("boom")))
    client = SimpleNamespace(models=models, close=close)
    monkeypatch.setattr(provider, "_client", lambda timeout=30: client)
    monkeypatch.setattr(openrouter_provider_module, "APIError", Exception)

    result = await provider.fetch_models(timeout=2)

    assert result == []
    close.assert_awaited_once()


async def test_empty_discovery_closes_fetch_and_probe_clients(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    _ = isolated_secret_dir
    manager = ProviderManager()
    provider = manager.get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)
    provider.api_key = "sk-or-test"

    fetch_close = AsyncMock()
    probe_close = AsyncMock()
    fetch_client = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[])),
        ),
        close=fetch_close,
    )
    probe_client = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[])),
        ),
        close=probe_close,
    )
    clients = iter((fetch_client, probe_client))
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: next(clients),
    )

    result = await manager.discover_provider_models("openrouter")

    assert result.success is False
    assert result.error == "Provider returned no models"
    fetch_close.assert_awaited_once()
    probe_close.assert_awaited_once()
