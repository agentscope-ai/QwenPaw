# -*- coding: utf-8 -*-
"""Candidate selection and runtime reconstruction regression coverage."""

from unittest.mock import AsyncMock

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.anthropic_provider import AnthropicProvider
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.provider import Provider
from qwenpaw.providers.model_pool import ModelPoolQuery, model_pool_page
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider_manager import ProviderManager


async def test_catalog_is_candidate_until_selected(isolated_secret_dir):
    manager = ProviderManager()
    provider = manager.get_provider(f"deepseek")
    info = await provider.get_info()
    assert info.models == []
    card = next(
        model
        for model in info.discovered_models
        if model.id == f"deepseek-flash"
    )
    assert card.supports_image is True
    assert card.billing == f"paid"
    assert card.max_output_length == 384000
    assert card.effective_max_input_length == 1000000
    selected = await manager.update_model_pool(
        provider.id,
        card.id,
        selected=True,
        seen=True,
    )
    assert card.id in {model.id for model in selected.models}
    assert card.id in selected.seen_model_ids
    reloaded = ProviderManager().get_provider(provider.id)
    assert card.id in {
        model.id for model in (await reloaded.get_info()).models
    }
    deselected = await manager.update_model_pool(
        provider.id,
        card.id,
        selected=False,
    )
    assert card.id not in {model.id for model in deselected.models}
    assert card.id in {model.id for model in deselected.discovered_models}

    await manager.update_model_config(
        provider.id,
        card.id,
        {f"max_input_length": 64000},
    )
    enabled = await manager.select_all_models(provider.id, selected=True)
    pool_ids = {
        model.id
        for model in manager.get_provider(provider.id).discovery_candidates()
    }
    assert pool_ids <= {
        model.id for model in enabled.models + enabled.extra_models
    }
    await manager.save_active_model_async(
        ModelSlotConfig(provider_id=provider.id, model=card.id),
    )
    disabled = await manager.select_all_models(provider.id, selected=False)
    assert not disabled.models and not disabled.extra_models
    assert manager.get_active_model() is None
    reloaded = ProviderManager().get_provider(provider.id)
    retained = next(
        m for m in reloaded.discovery_candidates() if m.id == card.id
    )
    assert retained.max_input_length == 64000


async def test_new_free_discovery_never_selects_itself(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    remote = ModelInfo(
        id=f"vendor/new:free",
        name=f"New",
        billing=f"free",
        is_free=True,
        supports_tool_calling=True,
        ranking_id=f"z-ai/glm-5.3-flash",
    )
    monkeypatch.setattr(
        OpenRouterProvider,
        f"fetch_models",
        AsyncMock(return_value=[remote]),
    )
    assert (await manager.discover_provider_models(f"openrouter")).success
    info = await manager.get_provider(f"openrouter").get_info()
    assert not info.models and not info.extra_models
    assert remote.id in {model.id for model in info.discovered_models}
    assert remote.id not in info.seen_model_ids
    await manager.update_model_pool(f"openrouter", remote.id, seen=True)
    assert (await manager.discover_provider_models(f"openrouter")).success
    info = await ProviderManager().get_provider(f"openrouter").get_info()
    assert remote.id in info.seen_model_ids
    assert not info.models and not info.extra_models


async def test_listing_preserves_explicit_selection(isolated_secret_dir):
    manager = ProviderManager()
    manager.active_model = ModelSlotConfig(
        provider_id=f"deepseek",
        model=f"deepseek-flash",
    )
    await manager.add_model_to_provider(
        f"deepseek",
        ModelInfo(id=f"manual", name=f"Manual"),
    )
    info = next(
        provider
        for provider in await manager.list_provider_info()
        if provider.id == f"deepseek"
    )
    assert f"deepseek-flash" not in {model.id for model in info.models}
    assert f"manual" in {model.id for model in info.extra_models}


@pytest.mark.parametrize(f"operation", [f"config", f"discovery"])
async def test_cached_anthropic_client_is_not_copied(
    isolated_secret_dir,
    monkeypatch,
    operation,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"anthropic")
    provider.auth_mode = f"auth_token"
    client = provider._get_strip_http_client()
    monkeypatch.setattr(
        AnthropicProvider,
        f"fetch_models",
        AsyncMock(return_value=[ModelInfo(id=f"claude-test", name=f"Claude")]),
    )
    if operation == f"config":
        assert await manager.update_provider_async(
            provider.id,
            {f"api_key": f"replacement"},
        )
    else:
        assert (await manager.discover_provider_models(provider.id)).success
    rebuilt = manager.get_provider(provider.id)
    assert rebuilt is not provider
    assert rebuilt._strip_http_client is None
    assert client.is_closed
    assert not rebuilt.models_syncing


async def test_failed_save_keeps_live_client(isolated_secret_dir, monkeypatch):
    manager = ProviderManager()
    provider = manager.get_provider(f"anthropic")
    client = provider._get_strip_http_client()

    def fail(*args, **kwargs):
        raise OSError(f"Disk full")

    monkeypatch.setattr(manager, f"_save_provider_snapshot_locked", fail)
    with pytest.raises(OSError):
        await manager.update_provider_async(provider.id, {f"name": f"New"})
    assert manager.get_provider(provider.id) is provider
    assert not client.is_closed
    await provider.close()


async def test_read_receipt_keeps_runtime_client(isolated_secret_dir):
    manager = ProviderManager()
    provider = manager.get_provider(f"anthropic")
    client = provider._get_strip_http_client()
    model_id = provider.discovery_candidates()[0].id
    await manager.update_model_pool(provider.id, model_id, seen=True)
    assert manager.get_provider(provider.id) is provider
    assert not client.is_closed
    assert model_id in provider.seen_model_ids
    assert (
        model_id in ProviderManager().get_provider(provider.id).seen_model_ids
    )
    await provider.close()


async def test_overview_does_not_expand_candidate_catalog(
    isolated_secret_dir, monkeypatch
):
    def unexpected(_self):
        raise AssertionError(f"Overview must not load candidate shards")

    monkeypatch.setattr(Provider, f"discovery_candidates", unexpected)
    infos = await ProviderManager().list_provider_info()
    assert infos
    assert all(not info.discovered_models for info in infos)


async def test_candidate_config_survives_reload_without_selection(
    isolated_secret_dir,
):
    manager = ProviderManager()
    await manager.update_model_config(
        f"deepseek",
        f"deepseek-v4-flash-vision-exp",
        {f"max_input_length": 64000, f"supports_image": False},
    )
    provider = ProviderManager().get_provider(f"deepseek")
    assert not provider.configured_models()
    card = next(
        card
        for card in (await provider.get_info()).discovered_models
        if card.id == f"deepseek-v4-flash-vision-exp"
    )
    assert card.effective_max_input_length == 64000
    assert card.supports_image is False


async def test_pool_filters_before_paging_and_keeps_unknown_separate(
    isolated_secret_dir,
):
    provider = OpenRouterProvider(
        id=f"test",
        name=f"Test",
        base_url=f"https://example.test/v1",
        discovered_models=[
            ModelInfo(
                id=f"vendor/{i:03}",
                name=f"Model {i}",
                billing=f"free" if i % 2 else f"paid",
                supports_image=True if i % 2 else None,
            )
            for i in range(80)
        ],
    )
    page = model_pool_page(
        provider,
        ModelPoolQuery(
            billing=f"free",
            capability=f"image",
            offset=30,
            limit=10,
        ),
    )
    assert page.total == 40
    assert page.candidate_count == 80
    assert page.selected_count == 0
    assert [card.id for card in page.models] == [
        f"vendor/{i:03}" for i in range(61, 80, 2)
    ]


async def test_removed_api_candidates_disappear_but_selected_survive(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"openrouter")
    provider.discovered_models = [
        ModelInfo(id=name, name=name, discovery_origin=f"api")
        for name in (f"gone", f"chosen")
    ]
    provider.extra_models = [
        ModelInfo(
            id=f"chosen",
            name=f"Chosen",
            source=f"user",
            discovery_origin=f"api",
        )
    ]
    monkeypatch.setattr(
        OpenRouterProvider,
        f"fetch_models",
        AsyncMock(return_value=[ModelInfo(id=f"new", name=f"New")]),
    )
    result = await manager.discover_provider_models(f"openrouter")
    assert result.success
    provider = manager.get_provider(f"openrouter")
    pool = {card.id: card for card in provider.discovery_candidates()}
    assert f"gone" not in pool
    assert pool[f"chosen"].remote_missing
    assert f"chosen" in {card.id for card in provider.configured_models()}


def test_pool_orders_newest_first_and_preserves_undated_order():
    provider = OpenRouterProvider(
        id=f"test",
        name=f"Test",
        base_url=f"https://example.test/v1",
        discovered_models=[
            ModelInfo(id=f"z", name=f"Undated Z"),
            ModelInfo(id=f"a", name=f"Undated A"),
            ModelInfo(id=f"old", name=f"Old", released_at=f"2025-01-01"),
            ModelInfo(id=f"new", name=f"New", released_at=f"2026-09-01"),
        ],
    )
    page = model_pool_page(provider, ModelPoolQuery())
    assert [card.id for card in page.models] == [f"new", f"old", f"z", f"a"]


async def test_unselected_catalog_model_can_be_tested_and_persisted(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"deepseek")
    monkeypatch.setattr(
        type(provider),
        f"check_model_connection",
        AsyncMock(return_value=(True, f"Connected")),
    )
    result = await manager.check_provider_model(
        f"deepseek", f"deepseek-v4-flash-vision-exp"
    )
    assert result.success
    reloaded = ProviderManager().get_provider(f"deepseek")
    assert not reloaded.configured_models()
    card = reloaded.get_discovered_model_info(f"deepseek-v4-flash-vision-exp")
    assert card.availability_status == f"available"


def test_quick_filters_combine_before_pagination():
    provider = OpenRouterProvider(id=f"test", name=f"Test")
    provider._resolved_pool = [
        ModelInfo(
            id=f"model-{index}",
            name=f"Model {index}",
            billing=f"free" if index < 4 else f"paid",
            supports_image=index % 2 == 0,
            supports_multimodal=index % 2 == 0,
            supports_tool_calling=index != 0,
        )
        for index in range(6)
    ]
    page = model_pool_page(
        provider,
        ModelPoolQuery(
            billing=f"free",
            multimodal=True,
            tools=True,
            limit=1,
        ),
    )
    assert page.total == 1
    assert [card.id for card in page.models] == [f"model-2"]


def test_pro_candidates_include_unknown_prices_but_exclude_free():
    provider = OpenRouterProvider(id=f"test", name=f"Test")
    provider._resolved_pool = [
        ModelInfo(id=billing, name=billing, billing=billing)
        for billing in (f"free", f"paid", f"unknown")
    ]
    page = model_pool_page(provider, ModelPoolQuery(billing=f"pro"))
    assert [card.id for card in page.models] == [f"paid", f"unknown"]
