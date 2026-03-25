# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the Kimi built-in providers."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import copaw.providers.provider_manager as provider_manager_module
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider_manager import (
    KIMI_MODELS,
    PROVIDER_KIMI_CN,
    PROVIDER_KIMI_INTL,
    ProviderManager,
)


def test_kimi_providers_are_openai_compatible() -> None:
    """Kimi providers should be OpenAIProvider instances."""
    assert isinstance(PROVIDER_KIMI_CN, OpenAIProvider)
    assert isinstance(PROVIDER_KIMI_INTL, OpenAIProvider)


def test_kimi_provider_configs() -> None:
    """Verify Kimi provider configuration defaults."""
    assert PROVIDER_KIMI_CN.id == "kimi-cn"
    assert PROVIDER_KIMI_CN.name == "Kimi (China)"
    assert PROVIDER_KIMI_CN.base_url == "https://api.moonshot.cn/v1"
    assert PROVIDER_KIMI_CN.freeze_url is True

    assert PROVIDER_KIMI_INTL.id == "kimi-intl"
    assert PROVIDER_KIMI_INTL.name == "Kimi (International)"
    assert PROVIDER_KIMI_INTL.base_url == "https://api.moonshot.ai/v1"
    assert PROVIDER_KIMI_INTL.freeze_url is True


def test_kimi_models_list() -> None:
    """Verify Kimi model definitions."""
    model_ids = [m.id for m in KIMI_MODELS]
    assert "kimi-k2.5" in model_ids
    assert "kimi-k2-0905-preview" in model_ids
    assert "kimi-k2-0711-preview" in model_ids
    assert "kimi-k2-turbo-preview" in model_ids
    assert "kimi-k2-thinking" in model_ids
    assert "kimi-k2-thinking-turbo" in model_ids
    assert len(KIMI_MODELS) == 6


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".copaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_kimi_registered_in_provider_manager(isolated_secret_dir) -> None:
    """Kimi providers should be registered as built-in providers."""
    manager = ProviderManager()

    provider_cn = manager.get_provider("kimi-cn")
    assert provider_cn is not None
    assert isinstance(provider_cn, OpenAIProvider)
    assert provider_cn.base_url == "https://api.moonshot.cn/v1"

    provider_intl = manager.get_provider("kimi-intl")
    assert provider_intl is not None
    assert isinstance(provider_intl, OpenAIProvider)
    assert provider_intl.base_url == "https://api.moonshot.ai/v1"


async def test_kimi_check_connection_success(monkeypatch) -> None:
    """Kimi check_connection should delegate to OpenAI client."""
    provider = OpenAIProvider(
        id="kimi-cn",
        name="Kimi (China)",
        base_url="https://api.moonshot.cn/v1",
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


def test_kimi_has_expected_models(isolated_secret_dir) -> None:
    """Provider manager Kimi providers should include all built-in models."""
    manager = ProviderManager()
    provider_cn = manager.get_provider("kimi-cn")
    provider_intl = manager.get_provider("kimi-intl")

    assert provider_cn is not None
    assert provider_intl is not None

    for model_id in [
        "kimi-k2.5",
        "kimi-k2-0905-preview",
        "kimi-k2-0711-preview",
        "kimi-k2-turbo-preview",
        "kimi-k2-thinking",
        "kimi-k2-thinking-turbo",
    ]:
        assert provider_cn.has_model(model_id)
        assert provider_intl.has_model(model_id)


async def test_kimi_activate_models(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """Should be able to activate both Kimi providers."""
    manager = ProviderManager()

    await manager.activate_model("kimi-cn", "kimi-k2.5")
    assert manager.active_model is not None
    assert manager.active_model.provider_id == "kimi-cn"
    assert manager.active_model.model == "kimi-k2.5"

    await manager.activate_model("kimi-intl", "kimi-k2-thinking")
    assert manager.active_model is not None
    assert manager.active_model.provider_id == "kimi-intl"
    assert manager.active_model.model == "kimi-k2-thinking"
