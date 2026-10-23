# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for OpenRouter provider resource management."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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

    with pytest.raises(RuntimeError, match=f"boom"):
        await provider.fetch_models(timeout=2)
    close.assert_awaited_once()


async def test_empty_discovery_closes_client_without_probing(
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
    probe_close.assert_not_awaited()


@pytest.mark.parametrize(f"extended", [False, True])
def test_discovery_always_reads_capabilities(extended):
    payload = SimpleNamespace(
        data=[
            SimpleNamespace(
                id=f"vendor/vision",
                architecture={
                    f"input_modalities": [f"text", f"image", f"audio"],
                    f"output_modalities": [f"text"],
                },
                supported_parameters=[f"tools"],
            ),
        ],
    )
    model = OpenRouterProvider._normalize_models_payload(
        payload,
        include_extended=extended,
    )[0]
    assert model.supports_image is True
    assert model.supports_audio is True
    assert model.supports_video is False
    assert model.supports_tool_calling is True
    assert model.probe_source == f"api"


def test_missing_modalities_remain_unknown():
    payload = SimpleNamespace(data=[SimpleNamespace(id=f"vendor/unknown")])
    model = OpenRouterProvider._normalize_models_payload(payload)[0]
    assert model.supports_image is None
    assert model.supports_audio is None
    assert model.supports_tool_calling is None
