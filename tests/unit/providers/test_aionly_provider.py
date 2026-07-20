# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the AIOnly built-in provider."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    AIONLY_MODELS,
    PROVIDER_AIONLY,
    ProviderManager,
)


def test_aionly_provider_is_openai_compatible() -> None:
    """AIOnly provider should be an OpenAIProvider instance."""
    assert isinstance(PROVIDER_AIONLY, OpenAIProvider)


def test_aionly_provider_configs() -> None:
    """Verify AIOnly provider configuration defaults."""
    assert PROVIDER_AIONLY.id == "aionly"
    assert PROVIDER_AIONLY.name == "AIOnly"
    assert PROVIDER_AIONLY.base_url == "https://api.aionly.com/v1"
    assert PROVIDER_AIONLY.api_key_prefix == "sk-"
    assert PROVIDER_AIONLY.freeze_url is True
    assert PROVIDER_AIONLY.support_model_discovery is False
    assert PROVIDER_AIONLY.require_api_key is True
    assert PROVIDER_AIONLY.is_local is False


def test_aionly_models_list() -> None:
    """Verify AIOnly has preset models with expected entries."""
    assert len(AIONLY_MODELS) == 19
    model_ids = {m.id for m in AIONLY_MODELS}
    # Spot-check representative models across families.
    for expected_id in [
        "kimi-k3",
        "gpt-5.6-luna",
        "grok-4.5",
        "claude-sonnet-5",
        "qwen3.7-plus",
        "glm-5.2",
        "deepseek-v4-pro",
        "gemini-3.5-flash",
        "gpt-5.5",
    ]:
        assert expected_id in model_ids

    # All preset models should carry documentation-sourced capabilities.
    for model in AIONLY_MODELS:
        assert model.probe_source == "documentation"
        assert model.max_tokens >= 1
        assert model.max_input_length >= 1000


def test_aionly_models_have_valid_capability_flags() -> None:
    """Vision-capable families should be flagged consistently."""
    vision_ids = {
        "kimi-k3",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "grok-4.5",
        "claude-sonnet-5",
        "grok-4.3",
        "qwen3.7-plus",
        "claude-fable-5",
        "claude-opus-4-8",
        "gemini-3.5-flash",
        "kimi-k2.6",
        "gpt-5.5",
    }
    for model in AIONLY_MODELS:
        if model.id in vision_ids:
            assert model.supports_image is True, model.id


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_aionly_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """AIOnly provider should be registered as a built-in provider."""
    manager = ProviderManager()

    provider = manager.get_provider("aionly")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == "https://api.aionly.com/v1"
    assert provider.support_model_discovery is False


@pytest.mark.asyncio
async def test_aionly_check_connection_success(monkeypatch) -> None:
    """AIOnly check_connection should delegate to the OpenAI client."""
    provider = OpenAIProvider(
        id="aionly",
        name="AIOnly",
        base_url="https://api.aionly.com/v1",
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
