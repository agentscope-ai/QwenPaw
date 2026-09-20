# -*- coding: utf-8 -*-
"""Provider pricing hooks and manual fallback provenance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.openai_provider import (
    OpenAIProvider,
    OpenCodeProvider,
    KiloProvider,
)
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider_catalog import PROVIDER_SILICONFLOW_CN
from qwenpaw.providers.provider_discovery import merge_discovered_model


@pytest.mark.parametrize(
    f"provider,model_id",
    [
        (OpenCodeProvider, f"model-free"),
        (KiloProvider, f"model:free"),
    ],
)
def test_service_free_routes_never_override_positive_api_price(
    provider,
    model_id,
):
    row = SimpleNamespace(id=model_id)
    assert provider.parse_model_pricing(row)[f"billing"] == f"free"
    row.pricing = {f"prompt": f"1", f"completion": f"1"}
    assert provider.parse_model_pricing(row)[f"billing"] == f"paid"
    assert (
        OpenAIProvider.parse_model_pricing(
            SimpleNamespace(id=model_id),
        )[f"billing"]
        == f"unknown"
    )


def test_openrouter_preserves_prices_without_extended_mode():
    row = SimpleNamespace(
        id=f"vendor/model",
        pricing={f"prompt": f"0", f"completion": f"0"},
    )
    card = OpenRouterProvider._normalize_models_payload(
        SimpleNamespace(data=[row]),
    )[0]
    assert card.pricing == row.pricing
    assert card.billing_source == f"api"


async def test_pricing_fetch_uses_existing_response(monkeypatch):
    provider = PROVIDER_SILICONFLOW_CN.model_copy(deep=True)
    fetch = AsyncMock(side_effect=AssertionError(f"Duplicate API call"))
    monkeypatch.setattr(type(provider), f"fetch_models", fetch)
    model = ModelInfo(id=f"Qwen/Qwen3.5-4B", name=f"Qwen")
    prices = await provider.fetch_model_pricing([model])
    card = prices[model.id]
    assert card.billing == f"free"
    assert card.billing_source == f"catalog"
    assert f"not automatically" in (
        card.capability_provenance[f"billing"][f"note"]
    )
    assert model.billing == f"unknown"
    fetch.assert_not_called()
    merged = merge_discovered_model(provider, card, f"2026-09-20T00:00:00Z")
    assert merged.billing_source == f"catalog"
    assert merged.billing_checked_at is None


async def test_pricing_fetch_can_query_endpoint(monkeypatch):
    provider = OpenAIProvider(id=f"plugin", name=f"Plugin")
    model = ModelInfo(
        id=f"new",
        name=f"New",
        billing=f"paid",
        billing_source=f"api",
        pricing={f"prompt": f"0.1"},
    )
    fetch = AsyncMock(return_value=[model])
    monkeypatch.setattr(type(provider), f"fetch_models", fetch)
    prices = await provider.fetch_model_pricing(timeout=3)
    fetch.assert_awaited_once_with(timeout=3)
    assert prices[model.id].pricing == model.pricing
    assert prices[model.id].billing_source == f"api"


async def test_endpoint_price_wins_over_manual_free_preset():
    provider = PROVIDER_SILICONFLOW_CN.model_copy(deep=True)
    model = ModelInfo(
        id=f"Qwen/Qwen3.5-4B",
        name=f"Qwen",
        billing=f"paid",
        billing_source=f"api",
        pricing={f"prompt": f"1"},
    )
    prices = await provider.fetch_model_pricing([model])
    assert prices[model.id].billing == f"paid"
    assert prices[model.id].billing_source == f"api"


async def test_custom_endpoint_does_not_inherit_service_price():
    provider = PROVIDER_SILICONFLOW_CN.model_copy(deep=True)
    provider.base_url = f"https://custom.example/v1"
    model = ModelInfo(id=f"Qwen/Qwen3.5-4B", name=f"Qwen")
    prices = await provider.fetch_model_pricing([model])
    assert prices[model.id].billing == f"unknown"
