# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the MiniMax built-in provider."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import copaw.providers.provider_manager as provider_manager_module
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider_manager import (
    MINIMAX_MODELS,
    PROVIDER_MINIMAX,
    ProviderManager,
)


def test_minimax_provider_is_openai_compatible() -> None:
    """MiniMax provider should be an OpenAIProvider instance."""
    assert isinstance(PROVIDER_MINIMAX, OpenAIProvider)


def test_minimax_provider_config() -> None:
    """Verify MiniMax provider configuration defaults."""
    assert PROVIDER_MINIMAX.id == "minimax"
    assert PROVIDER_MINIMAX.name == "MiniMax"
    assert PROVIDER_MINIMAX.base_url == "https://api.minimax.io/v1"
    assert PROVIDER_MINIMAX.freeze_url is True
    assert PROVIDER_MINIMAX.generate_kwargs == {"temperature": 1.0}


def test_minimax_models_list() -> None:
    """Verify MiniMax model definitions."""
    model_ids = [m.id for m in MINIMAX_MODELS]
    assert "MiniMax-M2.5" in model_ids
    assert "MiniMax-M2.5-highspeed" in model_ids
    assert len(MINIMAX_MODELS) == 2


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".copaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_minimax_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """MiniMax should be registered as a built-in provider."""
    manager = ProviderManager()
    provider = manager.get_provider("minimax")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.id == "minimax"
    assert provider.base_url == "https://api.minimax.io/v1"


async def test_minimax_check_connection_success(monkeypatch) -> None:
    """MiniMax check_connection should delegate to OpenAI client."""
    provider = OpenAIProvider(
        id="minimax",
        name="MiniMax",
        base_url="https://api.minimax.io/v1",
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


def test_minimax_has_expected_models(isolated_secret_dir) -> None:
    """Provider manager's MiniMax should include both models."""
    manager = ProviderManager()
    provider = manager.get_provider("minimax")
    assert provider.has_model("MiniMax-M2.5")
    assert provider.has_model("MiniMax-M2.5-highspeed")


async def test_minimax_activate_model(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """Should be able to activate a MiniMax model."""
    manager = ProviderManager()

    await manager.activate_model("minimax", "MiniMax-M2.5")

    assert manager.active_model is not None
    assert manager.active_model.provider_id == "minimax"
    assert manager.active_model.model == "MiniMax-M2.5"
