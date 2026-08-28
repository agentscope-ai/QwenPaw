# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for OpenRouter provider resource management."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider import ExtendedModelInfo
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

    with pytest.raises(RuntimeError, match="boom"):
        await provider.fetch_models(timeout=2)

    close.assert_awaited_once()


def test_available_providers_from_existing_models() -> None:
    provider = _make_provider()
    models = [
        ExtendedModelInfo(
            id="openai/gpt-test",
            name="GPT Test",
            provider="openai",
        ),
        ExtendedModelInfo(
            id="google/gemini-test",
            name="Gemini Test",
            provider="google",
        ),
        ExtendedModelInfo(
            id="openai/gpt-other",
            name="GPT Other",
            provider="openai",
        ),
        ExtendedModelInfo(id="unowned", name="Unowned"),
    ]

    result = provider.available_providers_from_models(models)

    assert result == ["google", "openai"]


async def test_empty_discovery_succeeds_and_closes_clients(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    _ = isolated_secret_dir
    manager = ProviderManager()
    provider = manager.get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)
    provider.api_key = "sk-or-test"

    fetch_close = AsyncMock()
    fetch_client = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[])),
        ),
        close=fetch_close,
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda timeout=30: fetch_client,
    )

    result = await manager.discover_provider_models("openrouter")

    assert result.success is True
    assert result.models == []
    assert result.discovered_count == 0
    assert result.error is None
    fetch_close.assert_awaited_once()
