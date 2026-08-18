# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Tests for provider discovery policy and model visibility preferences."""

from __future__ import annotations

from unittest.mock import AsyncMock

from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.provider_catalog import BUILTIN_PROVIDERS
from qwenpaw.providers.provider_discovery_policy import (
    BUILTIN_DISCOVERY_POLICIES,
)
from qwenpaw.providers.provider_manager import ProviderManager


def test_every_builtin_provider_has_discovery_policy() -> None:
    provider_ids = {provider.id for provider in BUILTIN_PROVIDERS}

    assert set(BUILTIN_DISCOVERY_POLICIES) == provider_ids
    assert all(provider.discovery_strategy for provider in BUILTIN_PROVIDERS)


def test_catalog_only_provider_reports_reason() -> None:
    provider = next(
        item for item in BUILTIN_PROVIDERS if item.id == "aliyun-tokenplan"
    )

    assert provider.discovery_strategy == "catalog_only"
    assert provider.support_model_discovery is False
    assert provider.discovery_support_reason


def test_github_models_uses_catalog_only_policy() -> None:
    provider = next(
        item for item in BUILTIN_PROVIDERS if item.id == "github-models"
    )

    assert provider.discovery_strategy == "catalog_only"
    assert provider.model_sync_mode == "manual"
    assert provider.discovery_requires_auth is True
    assert provider.support_model_discovery is False
    assert provider.discovery_support_reason
    assert provider.models


def test_dynamic_policy_enables_previously_disabled_openai_provider() -> None:
    provider = next(
        item for item in BUILTIN_PROVIDERS if item.id == "volcengine-cn"
    )

    assert provider.discovery_strategy == "openai_models"
    assert provider.support_model_discovery is True


def test_hidden_models_are_filtered_without_deleting_cache() -> None:
    provider = next(
        item.model_copy(deep=True)
        for item in BUILTIN_PROVIDERS
        if item.id == "openai"
    )
    provider.models = []
    provider.discovered_models = [
        ModelInfo(id="visible", name="Visible"),
        ModelInfo(id="hidden", name="Hidden"),
    ]
    provider.hidden_model_ids = ["hidden"]

    assert [model.id for model in provider.discovery_candidates()] == [
        "visible",
    ]
    assert [model.id for model in provider.discovered_models] == [
        "visible",
        "hidden",
    ]


async def test_model_visibility_preference_persists(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()

    await manager.set_model_hidden("openai", "candidate", hidden=True)

    provider = manager.get_provider("openai")
    assert provider is not None
    assert provider.hidden_model_ids == ["candidate"]
    reloaded = ProviderManager().get_provider("openai")
    assert reloaded is not None
    assert reloaded.hidden_model_ids == ["candidate"]


async def test_startup_sync_runs_only_eligible_providers(
    isolated_secret_dir,
) -> None:
    manager = ProviderManager()
    openrouter = manager.get_provider("openrouter")
    assert openrouter is not None
    openrouter.api_key = "key"
    manager.discover_provider_models = AsyncMock()

    await manager.sync_startup_provider_models()

    synced_ids = {
        call.args[0]
        for call in manager.discover_provider_models.await_args_list
    }
    assert "openrouter" in synced_ids
    assert "ollama" in synced_ids
    assert "github-models" not in synced_ids
    assert "aliyun-tokenplan" not in synced_ids
