# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=no-name-in-module
"""Tests for the Volcengine built-in providers."""

from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_VOLCENGINE_CN,
    PROVIDER_VOLCENGINE_CN_AGENTPLAN,
    PROVIDER_VOLCENGINE_CN_CODINGPLAN,
    VOLCENGINE_AGENTPLAN_MODELS,
    VOLCENGINE_CODINGPLAN_MODELS,
    VOLCENGINE_MODELS,
    ProviderManager,
)


def test_volcengine_providers_are_openai_compatible() -> None:
    """Volcengine providers should be OpenAIProvider instances."""
    assert isinstance(PROVIDER_VOLCENGINE_CN, OpenAIProvider)
    assert isinstance(PROVIDER_VOLCENGINE_CN_CODINGPLAN, OpenAIProvider)
    assert isinstance(PROVIDER_VOLCENGINE_CN_AGENTPLAN, OpenAIProvider)


def test_volcengine_provider_configs() -> None:
    """Verify Volcengine provider configuration defaults."""
    assert PROVIDER_VOLCENGINE_CN.id == "volcengine-cn"
    assert PROVIDER_VOLCENGINE_CN.name == "Volcengine"
    assert (
        PROVIDER_VOLCENGINE_CN.base_url
        == "https://ark.cn-beijing.volces.com/api/v3"
    )
    assert PROVIDER_VOLCENGINE_CN.freeze_url is True
    assert PROVIDER_VOLCENGINE_CN.support_connection_check is True
    assert PROVIDER_VOLCENGINE_CN.support_model_discovery is True

    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.id == "volcengine-cn-codingplan"
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.name == "Volcengine Coding Plan"
    assert (
        PROVIDER_VOLCENGINE_CN_CODINGPLAN.base_url
        == "https://ark.cn-beijing.volces.com/api/coding/v3"
    )
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.freeze_url is True
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.support_connection_check is False
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.support_model_discovery is False


def test_volcengine_agentplan_provider_config() -> None:
    """Verify Volcengine Agent Plan provider configuration defaults."""
    assert PROVIDER_VOLCENGINE_CN_AGENTPLAN.id == "volcengine-cn-agentplan"
    assert PROVIDER_VOLCENGINE_CN_AGENTPLAN.name == "Volcengine Agent Plan"
    assert (
        PROVIDER_VOLCENGINE_CN_AGENTPLAN.base_url
        == "https://ark.cn-beijing.volces.com/api/plan/v3"
    )
    assert PROVIDER_VOLCENGINE_CN_AGENTPLAN.freeze_url is True
    assert PROVIDER_VOLCENGINE_CN_AGENTPLAN.support_connection_check is False
    assert PROVIDER_VOLCENGINE_CN_AGENTPLAN.support_model_discovery is False


def test_volcengine_models_list() -> None:
    """Verify Volcengine model definitions."""
    model_ids = [m.id for m in VOLCENGINE_MODELS]
    assert "doubao-seed-2-0-code-preview-260215" in model_ids
    assert len(VOLCENGINE_MODELS) == 16
    assert len(VOLCENGINE_CODINGPLAN_MODELS) == 9
    # Coding Plan: glm-5.3 live; glm-5.2 "deprecating soon"
    # (docs updated 2026-08-18).
    codingplan_ids = [m.id for m in VOLCENGINE_CODINGPLAN_MODELS]
    assert "glm-5.3" in codingplan_ids
    assert "glm-5.2" not in codingplan_ids


def test_volcengine_agentplan_models_list() -> None:
    """Agent Plan seed list: 11 currently-active models per official docs."""
    model_ids = [m.id for m in VOLCENGINE_AGENTPLAN_MODELS]
    assert len(model_ids) == 11
    expected = [
        "doubao-seed-2.0-lite",
        "doubao-seed-2.0-mini",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "minimax-m3",
        "glm-5.3",
        "doubao-seed-2.1-turbo",
        "doubao-seed-evolving",
        "kimi-k3",
        "kimi-k2.7-code",
        "ark-code-latest",
    ]
    assert model_ids == expected
    # Deprecated models must NOT be seeded
    assert "doubao-seed-2-0-code-preview-260215" not in model_ids
    assert "doubao-seed-2-0-pro-260215" not in model_ids
    assert "minimax-m2.7" not in model_ids
    assert "kimi-k2.6" not in model_ids
    assert "glm-5.2" not in model_ids


def test_volcengine_agentplan_model_limits() -> None:
    """Agent Plan model limits should follow the official docs."""
    limits = {
        m.id: (m.max_input_length, m.max_tokens)
        for m in VOLCENGINE_AGENTPLAN_MODELS
    }
    assert limits["doubao-seed-2.0-lite"] == (256 * 1024, 128 * 1024)
    assert limits["deepseek-v4-flash"] == (1024 * 1024, 384 * 1024)
    assert limits["minimax-m3"] == (1024 * 1024, 128 * 1024)
    assert limits["glm-5.3"] == (1024 * 1024, 128 * 1024)
    assert limits["kimi-k3"] == (1024 * 1024, 128 * 1024)
    assert limits["kimi-k2.7-code"] == (256 * 1024, 32 * 1024)
    # Auto-routing model: limits per official OpenCode recommendation
    assert limits["ark-code-latest"] == (256 * 1024, 32 * 1024)


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    """Provide an isolated secret dir for provider tests."""
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_volcengine_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """Volcengine providers should be registered as built-in providers."""
    manager = ProviderManager()

    provider_cn = manager.get_provider("volcengine-cn")
    assert provider_cn is not None
    assert isinstance(provider_cn, OpenAIProvider)
    assert provider_cn.base_url == "https://ark.cn-beijing.volces.com/api/v3"

    provider_codingplan = manager.get_provider(
        "volcengine-cn-codingplan",
    )
    assert provider_codingplan is not None
    assert isinstance(provider_codingplan, OpenAIProvider)
    assert (
        provider_codingplan.base_url
        == "https://ark.cn-beijing.volces.com/api/coding/v3"
    )

    provider_agentplan = manager.get_provider("volcengine-cn-agentplan")
    assert provider_agentplan is not None
    assert isinstance(provider_agentplan, OpenAIProvider)
    assert (
        provider_agentplan.base_url
        == "https://ark.cn-beijing.volces.com/api/plan/v3"
    )


def test_volcengine_has_expected_models(isolated_secret_dir) -> None:
    """Volcengine providers should include built-in models."""
    manager = ProviderManager()
    provider_cn = manager.get_provider("volcengine-cn")
    provider_codingplan = manager.get_provider(
        "volcengine-cn-codingplan",
    )
    provider_agentplan = manager.get_provider("volcengine-cn-agentplan")

    assert provider_cn is not None
    assert provider_codingplan is not None
    assert provider_agentplan is not None

    assert provider_cn.has_model("doubao-seed-2-0-code-preview-260215")
    assert provider_codingplan.has_model("doubao-seed-2.1-turbo")
    assert provider_codingplan.has_model("ark-code-latest")
    assert provider_agentplan.has_model("doubao-seed-2.0-lite")
    assert provider_agentplan.has_model("ark-code-latest")


def test_volcengine_agentplan_has_expected_models(
    isolated_secret_dir,
) -> None:
    """Agent Plan provider should include the full seed list."""
    manager = ProviderManager()
    provider = manager.get_provider("volcengine-cn-agentplan")
    assert provider is not None
    for model in VOLCENGINE_AGENTPLAN_MODELS:
        assert provider.has_model(model.id)
