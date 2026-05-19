# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the OpenCode Go built-in provider."""
from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_OPENCODE_GO,
    OPENCODE_GO_MODELS,
    ProviderManager,
)


def test_opencode_go_provider_is_openai_compatible() -> None:
    """OpenCode Go provider should be an OpenAIProvider instance."""
    assert isinstance(PROVIDER_OPENCODE_GO, OpenAIProvider)


def test_opencode_go_provider_configs() -> None:
    """Verify OpenCode Go provider configuration defaults."""
    assert PROVIDER_OPENCODE_GO.id == "opencode-go"
    assert PROVIDER_OPENCODE_GO.name == "OpenCode Go"
    assert PROVIDER_OPENCODE_GO.base_url == "https://opencode.ai/zen/go/v1"
    assert PROVIDER_OPENCODE_GO.freeze_url is True
    assert PROVIDER_OPENCODE_GO.support_connection_check is False
    assert PROVIDER_OPENCODE_GO.support_model_discovery is False
    assert PROVIDER_OPENCODE_GO.api_key_prefix == ""


def test_opencode_go_models_list() -> None:
    """Verify OpenCode Go model definitions."""
    model_ids = [m.id for m in OPENCODE_GO_MODELS]

    # Check key models exist
    assert "glm-5.1" in model_ids
    assert "glm-5" in model_ids
    assert "deepseek-v4-flash" in model_ids
    assert "deepseek-v4-pro" in model_ids
    assert "qwen3.6-plus" in model_ids
    assert "qwen3.5-plus" in model_ids
    assert "kimi-k2.5" in model_ids
    assert "kimi-k2.6" in model_ids
    assert "mimo-v2.5" in model_ids
    assert "mimo-v2.5-pro" in model_ids

    # Verify total count
    assert len(OPENCODE_GO_MODELS) == 10

    # Multimodal support: only Qwen and Kimi models
    multimodal_models = {
        "kimi-k2.5",
        "kimi-k2.6",
        "qwen3.6-plus",
        "qwen3.5-plus",
    }
    for m in OPENCODE_GO_MODELS:
        if m.id in multimodal_models:
            assert m.supports_image is True, f"{m.id} should support image"
            assert m.supports_video is True, f"{m.id} should support video"
        else:
            assert (
                m.supports_image is False
            ), f"{m.id} should not support image"
            assert (
                m.supports_video is False
            ), f"{m.id} should not support video"


def test_opencode_go_models_uniqueness() -> None:
    """Model IDs should be unique."""
    model_ids = [m.id for m in OPENCODE_GO_MODELS]
    assert len(model_ids) == len(set(model_ids)), "Duplicate model IDs found"


def test_opencode_go_models_probe_source() -> None:
    """All models should have probe_source='documentation'."""
    for m in OPENCODE_GO_MODELS:
        assert (
            m.probe_source == "documentation"
        ), f"{m.id} has wrong probe_source"


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_opencode_go_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """OpenCode Go provider should be registered as a built-in provider."""
    manager = ProviderManager()

    provider = manager.get_provider("opencode-go")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == "https://opencode.ai/zen/go/v1"
