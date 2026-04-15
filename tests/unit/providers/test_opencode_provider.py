# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the OpenCode built-in provider."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import (
    PROVIDER_OPENCODE,
    ProviderManager,
)


def test_opencode_provider_is_openai_compatible() -> None:
    """OpenCode provider should be an OpenAIProvider instance."""
    assert isinstance(PROVIDER_OPENCODE, OpenAIProvider)


def test_opencode_provider_config() -> None:
    """Verify OpenCode provider configuration defaults."""
    assert PROVIDER_OPENCODE.id == "opencode"
    assert PROVIDER_OPENCODE.name == "OpenCode"
    assert PROVIDER_OPENCODE.base_url == "https://opencode.ai/zen/v1"
    assert PROVIDER_OPENCODE.freeze_url is True
    assert PROVIDER_OPENCODE.support_model_discovery is False


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


def test_opencode_registered_in_provider_manager(isolated_secret_dir) -> None:
    """OpenCode provider should be registered as built-in provider."""
    manager = ProviderManager()

    provider = manager.get_provider("opencode")
    assert provider is not None
    assert isinstance(provider, OpenAIProvider)
    assert provider.base_url == "https://opencode.ai/zen/v1"


async def test_opencode_check_connection_success(monkeypatch) -> None:
    """OpenCode check_connection should delegate to OpenAI client."""
    provider = OpenAIProvider(
        id="opencode",
        name="OpenCode",
        base_url="https://opencode.ai/zen/v1",
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


def test_opencode_has_expected_models(isolated_secret_dir) -> None:
    """Provider manager OpenCode provider should include built-in models."""
    manager = ProviderManager()
    provider = manager.get_provider("opencode")

    assert provider is not None

    for model_id in [
        "big-pickle",
        "nemotron-3-super-free",
    ]:
        assert provider.has_model(model_id)
