# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the OrcaRouter built-in provider."""
from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_ORCAROUTER,
    ProviderManager,
)


def test_orcarouter_provider_is_openai_compatible() -> None:
    """OrcaRouter provider should be an OpenAIProvider instance."""
    assert isinstance(PROVIDER_ORCAROUTER, OpenAIProvider)


def test_orcarouter_provider_config() -> None:
    """Verify OrcaRouter provider configuration defaults."""
    assert PROVIDER_ORCAROUTER.id == "orcarouter"
    assert PROVIDER_ORCAROUTER.name == "OrcaRouter"
    assert PROVIDER_ORCAROUTER.base_url == "https://api.orcarouter.ai/v1"
    assert PROVIDER_ORCAROUTER.freeze_url is True
    assert PROVIDER_ORCAROUTER.require_api_key is True
    assert PROVIDER_ORCAROUTER.api_key_prefix == "sk-orca-"


def test_orcarouter_ships_a_non_empty_preset_model_list() -> None:
    """Users should have working models before running Discover Models."""
    assert len(PROVIDER_ORCAROUTER.models) > 0
    for model in PROVIDER_ORCAROUTER.models:
        assert model.id
        assert model.name


def test_orcarouter_supports_model_discovery() -> None:
    """The full routed lineup changes upstream, so it is also fetchable."""
    assert PROVIDER_ORCAROUTER.support_model_discovery is True


def test_orcarouter_preset_model_ids_are_unique() -> None:
    """A duplicated preset id would show up twice in the model picker."""
    ids = [model.id for model in PROVIDER_ORCAROUTER.models]
    assert len(ids) == len(set(ids))


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_orcarouter_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """OrcaRouter provider should be registered as a built-in provider."""
    manager = ProviderManager()

    provider = manager.get_provider("orcarouter")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == "https://api.orcarouter.ai/v1"
    assert provider.name == "OrcaRouter"


def test_orcarouter_provider_list_includes_orcarouter(
    isolated_secret_dir,
) -> None:
    """ProviderManager should list OrcaRouter in available providers."""
    manager = ProviderManager()

    assert "orcarouter" in manager.builtin_providers
    assert manager.get_provider("orcarouter") is not None


def test_orcarouter_does_not_collide_with_openrouter(
    isolated_secret_dir,
) -> None:
    """OrcaRouter and OpenRouter are distinct routes with distinct hosts."""
    manager = ProviderManager()

    orca = manager.get_provider("orcarouter")
    openrouter = manager.get_provider("openrouter")
    assert orca is not None and openrouter is not None
    assert orca.id != openrouter.id
    assert orca.base_url != openrouter.base_url
