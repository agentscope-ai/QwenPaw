# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the SiliconFlow built-in providers."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_SILICONFLOW_CN,
    PROVIDER_SILICONFLOW_INTL,
    ProviderManager,
)


def test_siliconflow_providers_are_openai_compatible() -> None:
    """Siliconflow providers should be OpenAIProvider instances."""
    assert isinstance(PROVIDER_SILICONFLOW_CN, OpenAIProvider)
    assert isinstance(PROVIDER_SILICONFLOW_INTL, OpenAIProvider)


def test_siliconflow_provider_configs() -> None:
    """Verify Siliconflow provider configuration defaults."""
    assert PROVIDER_SILICONFLOW_CN.id == "siliconflow-cn"
    assert PROVIDER_SILICONFLOW_CN.name == "SiliconFlow (China)"
    assert PROVIDER_SILICONFLOW_CN.base_url == "https://api.siliconflow.cn/v1"
    assert PROVIDER_SILICONFLOW_CN.freeze_url is True
    assert PROVIDER_SILICONFLOW_CN.support_model_discovery is False

    assert PROVIDER_SILICONFLOW_INTL.id == "siliconflow-intl"
    assert PROVIDER_SILICONFLOW_INTL.name == "SiliconFlow (International)"
    assert (
        PROVIDER_SILICONFLOW_INTL.base_url == "https://api.siliconflow.com/v1"
    )
    assert PROVIDER_SILICONFLOW_INTL.freeze_url is True
    assert PROVIDER_SILICONFLOW_INTL.support_model_discovery is False


def test_siliconflow_models_list() -> None:
    """Verify Siliconflow has no preset models (empty list)."""
    assert PROVIDER_SILICONFLOW_CN.models == []
    assert PROVIDER_SILICONFLOW_INTL.models == []
    assert len(PROVIDER_SILICONFLOW_CN.models) == 0
    assert len(PROVIDER_SILICONFLOW_INTL.models) == 0


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_siliconflow_registered_in_provider_manager(
    isolated_secret_dir,
) -> None:
    """Siliconflow providers should be registered as built-in providers."""
    manager = ProviderManager()

    provider_cn = manager.get_provider("siliconflow-cn")
    assert provider_cn is not None
    assert isinstance(provider_cn, OpenAIProvider)
    assert provider_cn.base_url == "https://api.siliconflow.cn/v1"

    provider_intl = manager.get_provider("siliconflow-intl")
    assert provider_intl is not None
    assert isinstance(provider_intl, OpenAIProvider)
    assert provider_intl.base_url == "https://api.siliconflow.com/v1"


@pytest.mark.asyncio
async def test_siliconflow_check_connection_success(monkeypatch) -> None:
    """Siliconflow check_connection should delegate to OpenAI client."""
    provider = OpenAIProvider(
        id="siliconflow-cn",
        name="SiliconFlow (China)",
        base_url="https://api.siliconflow.cn/v1",
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
