# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=no-name-in-module
"""Tests for the Xiaomi MiMo built-in providers (Standard API + Token Plan)."""

from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.mimo_provider import MiMoProvider
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    MIMO_MODELS,
    MIMO_TOKENPLAN_MODELS,
    PROVIDER_MIMO,
    PROVIDER_MIMO_TOKENPLAN,
    ProviderManager,
)


def test_mimo_providers_are_openai_compatible() -> None:
    """MiMo providers should be OpenAIProvider instances."""
    assert isinstance(PROVIDER_MIMO_TOKENPLAN, OpenAIProvider)
    assert isinstance(PROVIDER_MIMO, OpenAIProvider)
    assert isinstance(PROVIDER_MIMO, MiMoProvider)


def test_mimo_tokenplan_provider_config() -> None:
    """Verify MiMo Token Plan provider configuration defaults."""
    assert PROVIDER_MIMO_TOKENPLAN.id == "mimo-tokenplan"
    assert PROVIDER_MIMO_TOKENPLAN.name == "Xiaomi MiMo Token Plan"
    assert (
        PROVIDER_MIMO_TOKENPLAN.base_url
        == "https://token-plan-cn.xiaomimimo.com/v1"
    )
    assert PROVIDER_MIMO_TOKENPLAN.freeze_url is True
    assert PROVIDER_MIMO_TOKENPLAN.api_key_prefix == ""


def test_mimo_standard_provider_config() -> None:
    """Verify MiMo Standard API provider configuration defaults."""
    assert PROVIDER_MIMO.id == "mimo"
    assert PROVIDER_MIMO.name == "Xiaomi MiMo"
    assert PROVIDER_MIMO.base_url == "https://api.xiaomimimo.com/v1"
    assert PROVIDER_MIMO.freeze_url is True
    assert PROVIDER_MIMO.api_key_prefix == "sk-"
    assert PROVIDER_MIMO.support_model_discovery is True


def test_mimo_models_list() -> None:
    """Verify MiMo model definitions."""
    tokenplan_ids = [m.id for m in MIMO_TOKENPLAN_MODELS]
    assert "mimo-v2.5-pro" in tokenplan_ids
    assert "mimo-v2.5" in tokenplan_ids
    assert len(MIMO_TOKENPLAN_MODELS) == 2

    standard_ids = [m.id for m in MIMO_MODELS]
    assert "mimo-v2.5-pro" in standard_ids
    assert "mimo-v2.5" in standard_ids
    assert len(MIMO_MODELS) == 2


def test_mimo_models_limits() -> None:
    """MiMo V2.5 chat models: 1M context / 128K output, per official docs."""
    for model in MIMO_TOKENPLAN_MODELS:
        assert model.max_input_length == 1024 * 1024
        assert model.max_output_length == 128 * 1024
    for model in MIMO_MODELS:
        assert model.max_input_length == 1024 * 1024
        assert model.max_output_length == 128 * 1024


def test_mimo_models_attributes() -> None:
    """Verify MiMo model attributes (multimodal flags per official docs)."""
    for model in MIMO_TOKENPLAN_MODELS:
        if model.id == "mimo-v2.5":
            assert model.supports_image is True
            assert model.supports_video is True
        else:
            assert model.supports_image is False
            assert model.supports_video is False
        assert model.probe_source == "documentation"
    for model in MIMO_MODELS:
        if model.id == "mimo-v2.5":
            assert model.supports_image is True
            assert model.supports_video is True
        else:
            assert model.supports_image is False
            assert model.supports_video is False


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    """Provide an isolated secret dir for provider tests."""
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_mimo_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """MiMo providers should be registered as built-in providers."""
    manager = ProviderManager()

    provider = manager.get_provider("mimo-tokenplan")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == "https://token-plan-cn.xiaomimimo.com/v1"
    assert provider.name == "Xiaomi MiMo Token Plan"

    provider_standard = manager.get_provider("mimo")
    assert provider_standard is not None
    assert isinstance(provider_standard, OpenAIProvider)
    assert provider_standard.base_url == "https://api.xiaomimimo.com/v1"
    assert provider_standard.name == "Xiaomi MiMo"


def test_mimo_has_expected_models(isolated_secret_dir) -> None:
    """MiMo providers should include built-in models."""
    manager = ProviderManager()
    provider = manager.get_provider("mimo-tokenplan")
    provider_standard = manager.get_provider("mimo")

    assert provider is not None
    assert provider_standard is not None
    assert provider.has_model("mimo-v2.5-pro")
    assert provider.has_model("mimo-v2.5")
    assert provider_standard.has_model("mimo-v2.5-pro")
    assert provider_standard.has_model("mimo-v2.5")


def test_mimo_provider_list_includes_mimo(isolated_secret_dir) -> None:
    """ProviderManager should list MiMo providers in available providers."""
    manager = ProviderManager()
    # Verify the providers exist in builtin_providers
    assert "mimo-tokenplan" in manager.builtin_providers
    assert "mimo" in manager.builtin_providers
    assert manager.get_provider("mimo-tokenplan") is not None
    assert manager.get_provider("mimo") is not None


def test_mimo_provider_filters_non_chat_models(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """MiMo discovery should filter ASR/TTS models and keep only chat ones.

    MiMo's ``/v1/models`` returns 6 models under the same ``object: model``
    type; the 4 non-chat ones (``-asr``/``-tts*``) must be filtered out by
    MiMoProvider.fetch_models before they surface as chat candidates.
    """
    manager = ProviderManager()
    provider = manager.get_provider("mimo")
    assert provider is not None
    assert isinstance(provider, MiMoProvider)

    chat_ids = ["mimo-v2.5", "mimo-v2.5-pro"]
    non_chat_ids = [
        "mimo-v2.5-asr",
        "mimo-v2.5-tts",
        "mimo-v2.5-tts-voiceclone",
        "mimo-v2.5-tts-voicedesign",
    ]

    # The reuse of OpenAIProvider._is_non_chat_model must classify MiMo's
    # non-chat models as non-chat (token keywords include asr/tts).
    from qwenpaw.providers.openai_provider import _is_non_chat_model

    for mid in chat_ids:
        assert _is_non_chat_model(mid) is False, mid
    for mid in non_chat_ids:
        assert _is_non_chat_model(mid) is True, mid

    async def fake_fetch(*args, **kwargs):  # noqa: ANN001, ANN002
        from qwenpaw.providers.provider import ModelInfo

        return [ModelInfo(id=mid, name=mid) for mid in chat_ids + non_chat_ids]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fake_fetch)
    import asyncio

    fetched = asyncio.run(provider.fetch_models(timeout=5))
    fetched_ids = [m.id for m in fetched]
    assert set(fetched_ids) == set(chat_ids)
