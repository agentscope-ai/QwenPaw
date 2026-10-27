# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=no-name-in-module
"""Tests for the Xiaomi MiMo built-in providers (Standard API + Token Plan)."""

from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.mimo_provider import MiMoProvider
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo
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
    expected = [
        "mimo-v2.6-pro",
        "mimo-v2.6-flash",
        "mimo-v2.5-pro",
        "mimo-v2.5",
    ]
    assert [m.id for m in MIMO_TOKENPLAN_MODELS] == expected[:2]
    assert [m.id for m in MIMO_MODELS] == expected


def test_mimo_models_limits() -> None:
    """MiMo V2.5/V2.6 chat models have 1M context and 128K output."""
    for model in MIMO_TOKENPLAN_MODELS:
        assert model.max_input_length == 1024 * 1024
        assert model.max_output_length == 128 * 1024
    for model in MIMO_MODELS:
        assert model.max_input_length == 1024 * 1024
        assert model.max_output_length == 128 * 1024


def test_mimo_models_attributes() -> None:
    """Verify MiMo model attributes (multimodal flags per official docs)."""
    expected = {
        "mimo-v2.6-pro": (True, True, True, "documentation"),
        "mimo-v2.6-flash": (True, True, True, "documentation"),
        "mimo-v2.5-pro": (False, False, None, "documentation"),
        "mimo-v2.5": (True, True, None, "documentation"),
    }
    assert {
        model.id: (
            model.supports_image,
            model.supports_video,
            model.supports_audio,
            model.probe_source,
        )
        for model in MIMO_MODELS
    } == expected
    assert {
        model.id: (
            model.supports_image,
            model.supports_video,
            model.supports_audio,
            model.probe_source,
        )
        for model in MIMO_TOKENPLAN_MODELS
    } == {
        "mimo-v2.6-pro": expected["mimo-v2.6-pro"],
        "mimo-v2.6-flash": expected["mimo-v2.6-flash"],
    }


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
    assert provider.has_model("mimo-v2.6-pro")
    assert provider.has_model("mimo-v2.6-flash")
    assert not provider.has_model("mimo-v2.5-pro")
    assert not provider.has_model("mimo-v2.5")
    assert provider_standard.has_model("mimo-v2.5-pro")
    assert provider_standard.has_model("mimo-v2.5")


@pytest.mark.parametrize("explicit_model", [False, True])
def test_mimo_tokenplan_upgrade_preserves_active_selection(
    isolated_secret_dir,
    explicit_model,
) -> None:
    """Keep saved selections without silently migrating retired defaults."""
    manager = ProviderManager()
    saved = PROVIDER_MIMO_TOKENPLAN.model_copy(deep=True)
    old = ModelInfo(
        id="mimo-v2.5-pro",
        name="MiMo V2.5 Pro",
        source="user" if explicit_model else "builtin",
    )
    saved.models = [] if explicit_model else [old]
    saved.extra_models = [old] if explicit_model else []
    manager._save_provider(saved, is_builtin=True)
    slot = ModelSlotConfig(provider_id=saved.id, model=old.id)
    manager.save_active_model(slot)

    restored = ProviderManager()
    provider = restored.get_provider(saved.id)
    assert provider is not None
    assert {
        "defaults": [model.id for model in provider.models],
        "extra_models": [model.id for model in provider.extra_models],
        "old_model_configured": provider.has_model(old.id),
        "active_model": restored.get_active_model(),
    } == {
        "defaults": ["mimo-v2.6-pro", "mimo-v2.6-flash"],
        "extra_models": [old.id] if explicit_model else [],
        "old_model_configured": explicit_model,
        "active_model": slot,
    }


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
        return [ModelInfo(id=mid, name=mid) for mid in chat_ids + non_chat_ids]

    monkeypatch.setattr(OpenAIProvider, "fetch_models", fake_fetch)
    import asyncio

    fetched = asyncio.run(provider.fetch_models(timeout=5))
    fetched_ids = [m.id for m in fetched]
    assert set(fetched_ids) == set(chat_ids)
