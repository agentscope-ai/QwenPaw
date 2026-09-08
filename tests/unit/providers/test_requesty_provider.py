# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=no-name-in-module
"""Tests for the Requesty built-in provider."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_REQUESTY,
    REQUESTY_MODELS,
    ProviderManager,
)
from qwenpaw.providers.requesty_provider import RequestyProvider


def test_requesty_provider_is_openai_compatible() -> None:
    """Requesty should be an OpenAIProvider subclass."""
    assert isinstance(PROVIDER_REQUESTY, OpenAIProvider)
    assert isinstance(PROVIDER_REQUESTY, RequestyProvider)


def test_requesty_provider_config() -> None:
    """Verify Requesty provider configuration defaults."""
    assert PROVIDER_REQUESTY.id == "requesty"
    assert PROVIDER_REQUESTY.name == "Requesty"
    assert PROVIDER_REQUESTY.base_url == "https://router.requesty.ai/v1"
    assert PROVIDER_REQUESTY.freeze_url is True
    assert PROVIDER_REQUESTY.support_model_discovery is True
    assert PROVIDER_REQUESTY.discovery_strategy == "openai_models"
    assert PROVIDER_REQUESTY.model_sync_mode == "startup"


def test_requesty_default_headers() -> None:
    """Attribution headers are sent; custom headers can override them."""
    headers = PROVIDER_REQUESTY._build_default_headers()
    assert headers["HTTP-Referer"] == "https://qwenpaw.agentscope.io/"
    assert headers["X-Title"] == "QwenPaw"

    provider = RequestyProvider(
        id="requesty",
        name="Requesty",
        base_url="https://router.requesty.ai/v1",
        api_key="test",
        custom_headers={"X-Title": "Custom", "X-Extra": "1"},
    )
    headers = provider._build_default_headers()
    assert headers["X-Title"] == "Custom"
    assert headers["X-Extra"] == "1"
    assert headers["HTTP-Referer"] == "https://qwenpaw.agentscope.io/"


def test_requesty_models_list() -> None:
    """Verify Requesty built-in model definitions use vendor/model ids."""
    ids = [m.id for m in REQUESTY_MODELS]
    assert "openai/gpt-4o-mini" in ids
    assert "anthropic/claude-sonnet-4-20250514" in ids
    assert "google/gemini-2.5-flash" in ids
    assert all("/" in model_id for model_id in ids)
    assert len(ids) == len(set(ids))
    for model in REQUESTY_MODELS:
        assert model.probe_source == "documentation"
        assert model.max_input_length is not None
        assert model.max_output_length is not None


def test_requesty_normalizes_models_payload() -> None:
    """Requesty's /v1/models field map is translated into ModelInfo."""
    payload = SimpleNamespace(
        data=[
            SimpleNamespace(
                id="openai/gpt-4o-mini",
                name="GPT-4o mini",
                api="chat",
                context_window=128000,
                max_output_tokens=16384,
                supports_vision=True,
            ),
            SimpleNamespace(
                id="deepseek/deepseek-chat",
                api="chat",
                context_window=131072,
                max_output_tokens=8192,
                supports_vision=False,
            ),
            SimpleNamespace(
                id="openai/text-embedding-3-small",
                api="embeddings",
                context_window=8192,
            ),
            SimpleNamespace(id="openai/gpt-4o-mini", api="chat"),
            SimpleNamespace(id="", api="chat"),
        ],
    )
    models = RequestyProvider._normalize_models_payload(payload)
    assert [model.id for model in models] == [
        "openai/gpt-4o-mini",
        "deepseek/deepseek-chat",
    ]
    first = models[0]
    assert first.name == "GPT-4o mini"
    assert first.max_input_length_auto_detected == 128000
    assert first.max_output_length == 16384
    assert first.supports_image is True
    assert first.probe_source == "documentation"
    second = models[1]
    assert second.name == "deepseek/deepseek-chat"
    assert second.supports_image is False


async def test_requesty_fetch_models_uses_normalizer(monkeypatch) -> None:
    """fetch_models should run the Requesty-specific payload normalizer."""
    provider = RequestyProvider(
        id="requesty",
        name="Requesty",
        base_url="https://router.requesty.ai/v1",
        api_key="test",
    )
    payload = SimpleNamespace(
        data=[
            SimpleNamespace(id="openai/gpt-4o-mini", api="chat"),
            SimpleNamespace(id="openai/tts-1", api="audio"),
        ],
    )

    class _Models:
        async def list(self, timeout=5):
            _ = timeout
            return payload

    class _Client:
        models = _Models()

        async def close(self):
            return None

    monkeypatch.setattr(provider, "_client", lambda timeout=5: _Client())
    models = await provider.fetch_models()
    assert [model.id for model in models] == ["openai/gpt-4o-mini"]


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    """Provide an isolated secret dir for provider tests."""
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_requesty_registered_in_provider_manager(isolated_secret_dir) -> None:
    """Requesty should be registered as a built-in provider."""
    manager = ProviderManager()
    assert "requesty" in manager.builtin_providers
    provider = manager.get_provider("requesty")
    assert provider is not None
    assert isinstance(provider, RequestyProvider)
    assert provider.base_url == "https://router.requesty.ai/v1"
    assert provider.has_model("openai/gpt-4o-mini")
