# -*- coding: utf-8 -*-
"""End-to-end discovery policy tests using isolated provider storage."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from qwenpaw.exceptions import ProviderError
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.model_sync import sync_due
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider_manager import ProviderManager


async def test_free_discovery_paid_transition_and_explicit_enable(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"openrouter")
    provider.api_key = f"test-key"
    provider.models = []
    provider.api_key = f"test-key"
    remote = ModelInfo(
        id=f"vendor/model",
        name=f"Model",
        is_free=True,
        billing=f"free",
        ranking_id=f"z-ai/glm-5.3-flash",
        supports_tool_calling=True,
    )
    fetch = AsyncMock(return_value=[remote])
    monkeypatch.setattr(OpenRouterProvider, f"fetch_models", fetch)
    assert (await manager.discover_provider_models(provider.id)).success
    assert provider.get_model_info(remote.id) is not None
    assert (await provider.get_info()).models[0].auto_enabled
    instance = provider.get_chat_model_instance(remote.id)
    remote.is_free = False
    remote.billing = f"paid"
    assert (await manager.discover_provider_models(provider.id)).success
    assert provider.get_model_info(remote.id) is None
    with pytest.raises(ProviderError, match=f"no longer confirmed free"):
        provider.check_model_billing(remote.id)
    with pytest.raises(ProviderError, match=f"no longer confirmed free"):
        await instance._call_api(remote.id, [])
    reloaded = ProviderManager().get_provider(provider.id)
    with pytest.raises(ProviderError):
        reloaded.check_model_billing(remote.id)
    await manager.add_model_to_provider(
        provider.id,
        ModelInfo(id=remote.id, name=remote.name),
    )
    provider.check_model_billing(remote.id)
    assert not provider.get_model_info(remote.id).auto_enabled


async def test_removed_free_model_does_not_return_after_sync_or_restart(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"openrouter")
    provider.api_key = f"test-key"
    remote = ModelInfo(
        id=f"vendor/free",
        name=f"Free",
        is_free=True,
        billing=f"free",
        ranking_id=f"z-ai/glm-5.3-flash",
        supports_tool_calling=True,
    )
    monkeypatch.setattr(
        OpenRouterProvider, f"fetch_models", AsyncMock(return_value=[remote])
    )
    await manager.discover_provider_models(provider.id)
    await manager.delete_model_from_provider(provider.id, remote.id)
    await manager.discover_provider_models(provider.id)
    assert provider.get_model_info(remote.id) is None
    assert remote.id in provider.removed_model_ids
    reloaded = ProviderManager().get_provider(provider.id)
    assert remote.id in reloaded.removed_model_ids
    assert reloaded.get_model_info(remote.id) is None


async def test_failed_sync_preserves_cache_but_complete_sync_marks_missing(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"openrouter")
    provider.api_key = f"test-key"
    remote = ModelInfo(
        id=f"vendor/free",
        name=f"Free",
        is_free=True,
        billing=f"free",
        ranking_id=f"z-ai/glm-5.3-flash",
        supports_tool_calling=True,
    )
    fetch = AsyncMock(return_value=[remote])
    monkeypatch.setattr(OpenRouterProvider, f"fetch_models", fetch)
    await manager.discover_provider_models(provider.id)
    fetch.side_effect = TimeoutError(f"timeout")
    assert not (await manager.discover_provider_models(provider.id)).success
    assert provider.get_model_info(remote.id) is not None
    fetch.side_effect = None
    fetch.return_value = [ModelInfo(id=f"other", name=f"Other")]
    await manager.discover_provider_models(provider.id)
    assert provider.get_model_info(remote.id) is None
    assert provider.get_discovered_model_info(remote.id).remote_missing
    with pytest.raises(ProviderError):
        provider.check_model_billing(remote.id)


def test_ttl_separates_free_inventory_and_paid_candidates():
    provider = OpenAIProvider(id=f"test", name=f"Test")
    provider.models_last_synced_at = (
        datetime.now(timezone.utc) - timedelta(hours=7)
    ).isoformat()
    assert not sync_due(provider)
    provider.models = [ModelInfo(id=f"free", name=f"Free", is_free=True)]
    assert sync_due(provider)


@pytest.mark.parametrize(
    f"pricing",
    [
        {},
        {f"prompt": f"0"},
        {f"prompt": f"0", f"completion": f"invalid"},
    ],
)
def test_incomplete_prices_never_claim_free(pricing):
    assert not OpenRouterProvider._is_free_model(pricing)


async def test_connection_change_invalidates_api_metadata(
    isolated_secret_dir,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"openai")
    model = provider.models[0]
    model.max_input_length_auto_detected = 900_000
    model.max_output_length = 16_000
    model.max_output_length_source = f"api"
    model.max_input_length_configured = True
    model.max_input_length = 64_000
    await manager.save_provider_config_async(provider.id)
    await manager.update_provider_async(provider.id, {f"api_key": f"new-key"})
    model = manager.get_provider(provider.id).models[0]
    assert model.max_input_length_auto_detected is None
    assert model.max_output_length_source != f"api"
    assert model.max_input_length_configured
    assert model.max_input_length == 64_000


async def test_curated_free_model_cannot_silently_become_paid(
    isolated_secret_dir,
    monkeypatch,
):
    manager = ProviderManager()
    provider = manager.get_provider(f"openrouter")
    provider.api_key = f"test-key"
    provider.models = [
        ModelInfo(
            id=f"curated-free",
            name=f"Curated",
            is_free=True,
            billing=f"free",
            ranking_id=f"z-ai/glm-5.3-flash",
            supports_tool_calling=True,
        )
    ]
    remote = ModelInfo(
        id=f"curated-free",
        name=f"Curated",
        is_free=False,
        billing=f"paid",
    )
    monkeypatch.setattr(
        OpenRouterProvider,
        f"fetch_models",
        AsyncMock(return_value=[remote]),
    )
    await manager.discover_provider_models(provider.id)
    with pytest.raises(ProviderError):
        provider.check_model_billing(remote.id)
