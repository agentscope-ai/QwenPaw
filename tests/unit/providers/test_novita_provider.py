# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the Novita AI built-in provider."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import copaw.providers.provider_manager as provider_manager_module
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider_manager import (
    NOVITA_MODELS,
    PROVIDER_NOVITA,
    ProviderManager,
)


def test_novita_provider_is_openai_compatible() -> None:
    """Novita provider should be an OpenAIProvider instance."""
    assert isinstance(PROVIDER_NOVITA, OpenAIProvider)


def test_novita_provider_config() -> None:
    """Verify Novita provider configuration defaults."""
    assert PROVIDER_NOVITA.id == "novita"
    assert PROVIDER_NOVITA.name == "Novita AI"
    assert PROVIDER_NOVITA.base_url == "https://api.novita.ai/openai"
    assert PROVIDER_NOVITA.freeze_url is True


def test_novita_models_list() -> None:
    """Verify Novita model definitions."""
    model_ids = [m.id for m in NOVITA_MODELS]
    assert "moonshotai/kimi-k2.5" in model_ids
    assert "zai-org/glm-5" in model_ids
    assert "minimax/minimax-m2.5" in model_ids
    assert len(NOVITA_MODELS) == 3


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".copaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_novita_registered_in_provider_manager(isolated_secret_dir) -> None:
    """Novita provider should be registered as a built-in provider."""
    manager = ProviderManager()

    provider = manager.get_provider("novita")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == "https://api.novita.ai/openai"


def test_novita_has_expected_models(isolated_secret_dir) -> None:
    """Provider manager Novita provider should include all built-in models."""
    manager = ProviderManager()
    provider = manager.get_provider("novita")

    assert provider is not None
    for model_id in [
        "moonshotai/kimi-k2.5",
        "zai-org/glm-5",
        "minimax/minimax-m2.5",
    ]:
        assert provider.has_model(model_id)


async def test_novita_check_connection_success(monkeypatch) -> None:
    """Novita check_connection should delegate to OpenAI client."""
    provider = OpenAIProvider(
        id="novita",
        name="Novita AI",
        base_url="https://api.novita.ai/openai",
        api_key="test-key",
    )

    class FakeModels:
        async def list(self, timeout=None):
            return SimpleNamespace(data=[])

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=2)

    assert ok is True
    assert msg == ""


async def test_novita_activate_model(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """Should be able to activate a Novita model."""
    manager = ProviderManager()

    await manager.activate_model("novita", "moonshotai/kimi-k2.5")
    assert manager.active_model is not None
    assert manager.active_model.provider_id == "novita"
    assert manager.active_model.model == "moonshotai/kimi-k2.5"
