# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the Volcano Engine built-in providers."""
from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_VOLCENGINE_CN,
    PROVIDER_VOLCENGINE_CN_CODINGPLAN,
    VOLCENGINE_MODELS,
    ProviderManager,
)


def test_volcengine_providers_are_openai_compatible() -> None:
    """Volcano Engine providers should be OpenAIProvider instances."""
    assert isinstance(PROVIDER_VOLCENGINE_CN, OpenAIProvider)
    assert isinstance(PROVIDER_VOLCENGINE_CN_CODINGPLAN, OpenAIProvider)


def test_volcengine_provider_configs() -> None:
    """Verify Volcano Engine provider configuration defaults."""
    assert PROVIDER_VOLCENGINE_CN.id == "volcengine-cn"
    assert PROVIDER_VOLCENGINE_CN.name == "Volcano Engine"
    assert (
        PROVIDER_VOLCENGINE_CN.base_url
        == "https://ark.cn-beijing.volces.com/api/v3"
    )
    assert PROVIDER_VOLCENGINE_CN.freeze_url is True
    assert PROVIDER_VOLCENGINE_CN.support_connection_check is True
    assert PROVIDER_VOLCENGINE_CN.support_model_discovery is False

    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.id == "volcengine-cn-codingplan"
    assert (
        PROVIDER_VOLCENGINE_CN_CODINGPLAN.name == "Volcano Engine Coding Plan"
    )
    assert (
        PROVIDER_VOLCENGINE_CN_CODINGPLAN.base_url
        == "https://ark.cn-beijing.volces.com/api/coding/v3"
    )
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.freeze_url is True
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.support_connection_check is False
    assert PROVIDER_VOLCENGINE_CN_CODINGPLAN.support_model_discovery is False


def test_volcengine_models_list() -> None:
    """Verify Volcano Engine model definitions."""
    model_ids = [m.id for m in VOLCENGINE_MODELS]
    assert "Doubao-Seed-2.0-Code" in model_ids
    assert len(VOLCENGINE_MODELS) == 10


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_volcengine_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """Volcano Engine providers should be registered as built-in providers."""
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


def test_volcengine_has_expected_models(isolated_secret_dir) -> None:
    """Volcano Engine providers should include built-in models."""
    manager = ProviderManager()
    provider_cn = manager.get_provider("volcengine-cn")
    provider_codingplan = manager.get_provider(
        "volcengine-cn-codingplan",
    )

    assert provider_cn is not None
    assert provider_codingplan is not None

    assert provider_cn.has_model("Doubao-Seed-2.0-Code")
    assert provider_codingplan.has_model("Doubao-Seed-2.0-Code")
