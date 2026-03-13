# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
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


def test_minimax_provider_definition():
    assert PROVIDER_MINIMAX.id == "minimax"
    assert PROVIDER_MINIMAX.name == "MiniMax"
    assert PROVIDER_MINIMAX.base_url == "https://api.minimaxi.com/v1"
    assert PROVIDER_MINIMAX.chat_model == "OpenAIChatModel"
    assert PROVIDER_MINIMAX.freeze_url is True
    assert isinstance(PROVIDER_MINIMAX, OpenAIProvider)


def test_minimax_models():
    assert len(MINIMAX_MODELS) == 2
    model_ids = [m.id for m in MINIMAX_MODELS]
    assert "MiniMax-M2.5" in model_ids
    assert "MiniMax-M2.5-highspeed" in model_ids


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".copaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_minimax_registered_as_builtin(isolated_secret_dir):
    manager = ProviderManager()
    provider = manager.get_provider("minimax")

    assert provider is not None
    assert provider.id == "minimax"
    assert provider.name == "MiniMax"
    assert isinstance(provider, OpenAIProvider)
    assert provider is PROVIDER_MINIMAX


async def test_minimax_listed_in_providers(isolated_secret_dir):
    manager = ProviderManager()
    infos = await manager.list_provider_info()
    provider_ids = [info.id for info in infos]

    assert "minimax" in provider_ids


def test_minimax_has_correct_models(isolated_secret_dir):
    manager = ProviderManager()
    provider = manager.get_provider("minimax")

    assert provider is not None
    assert provider.has_model("MiniMax-M2.5")
    assert provider.has_model("MiniMax-M2.5-highspeed")
    assert not provider.has_model("nonexistent-model")


def test_minimax_update_api_key_persists(isolated_secret_dir):
    manager = ProviderManager()

    ok = manager.update_provider("minimax", {"api_key": "test-minimax-key"})

    assert ok is True

    persisted = manager.load_provider("minimax", is_builtin=True)
    assert persisted is not None
    assert isinstance(persisted, OpenAIProvider)
    assert persisted.api_key == "test-minimax-key"
    assert persisted.base_url == "https://api.minimaxi.com/v1"


async def test_minimax_check_connection(monkeypatch, isolated_secret_dir):
    manager = ProviderManager()
    provider = manager.get_provider("minimax")

    class FakeModels:
        async def list(self, timeout=None):
            return SimpleNamespace(data=[])

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=2)

    assert ok is True
    assert msg == ""


async def test_minimax_activate_model(monkeypatch, isolated_secret_dir):
    manager = ProviderManager()

    await manager.activate_model("minimax", "MiniMax-M2.5")

    assert manager.active_model is not None
    assert manager.active_model.provider_id == "minimax"
    assert manager.active_model.model == "MiniMax-M2.5"

    reloaded = ProviderManager()
    assert reloaded.active_model is not None
    assert reloaded.active_model.provider_id == "minimax"
    assert reloaded.active_model.model == "MiniMax-M2.5"


async def test_minimax_activate_invalid_model_raises(isolated_secret_dir):
    manager = ProviderManager()

    with pytest.raises(ValueError, match="Model 'invalid' not found"):
        await manager.activate_model("minimax", "invalid")
