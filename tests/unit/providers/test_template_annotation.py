# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for applying documented capability templates to custom providers."""

from __future__ import annotations

import pytest

import qwenpaw.providers.provider_manager as provider_manager_module
from qwenpaw.providers.capability_baseline import ExpectedCapabilityRegistry
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo, ProviderInfo
from qwenpaw.providers.provider_annotations import ProviderAnnotationService
from qwenpaw.providers.provider_manager import ProviderManager


@pytest.fixture
def isolated_secret_dir(monkeypatch, tmp_path):
    secret_dir = tmp_path / ".qwenpaw.secret"
    monkeypatch.setattr(provider_manager_module, "SECRET_DIR", secret_dir)
    return secret_dir


async def test_add_known_model_to_custom_provider_applies_template(
    isolated_secret_dir,
) -> None:
    """Adding a documented model (qwen3.6-plus) to a custom provider
    should apply the documented capabilities so probing is skipped."""
    manager = ProviderManager()
    model_info = ModelInfo(id="qwen3.6-plus", name="Qwen3.6 Plus")

    await manager.add_model_to_provider("openai", model_info)
    provider = manager.get_provider("openai")
    added = next(m for m in provider.extra_models if m.id == "qwen3.6-plus")
    assert added.supports_image is True
    assert added.supports_video is True
    assert added.supports_multimodal is True
    assert added.probe_source == "documentation"


async def test_add_unknown_model_to_custom_provider_no_template(
    isolated_secret_dir,
) -> None:
    """Adding an undocumented model keeps capabilities unknown (None),
    so probing still applies as a fallback."""
    manager = ProviderManager()
    model_info = ModelInfo(id="brand-new-model-xyz", name="Brand New")

    await manager.add_model_to_provider("openai", model_info)
    provider = manager.get_provider("openai")
    added = next(
        m for m in provider.extra_models if m.id == "brand-new-model-xyz"
    )
    assert added.supports_image is None
    assert added.supports_video is None
    assert added.supports_multimodal is None


async def test_disk_custom_provider_gets_default_annotations(
    isolated_secret_dir,
) -> None:
    """A custom provider persisted on disk whose model is documented
    should be annotated on load (custom providers now included in
    _apply_default_annotations)."""
    manager = ProviderManager()
    model_info = ModelInfo(id="deepseek-v4-pro", name="DeepSeek V4 Pro")
    # Construct the provider record directly (no get_info round-trip) so the
    # persisted JSON carries null capabilities — the state of a
    # user-created / hand-edited provider file.  The init-time annotation is
    # what must fill it.
    provider_info = ProviderInfo(
        id="agentteams-gateway",
        name="AgentTeams Gateway",
        base_url="http://127.0.0.1:9999/v1",
        api_key="sk-test",
        extra_models=[model_info],
    )
    await manager.add_custom_provider(provider_info)

    reloaded = ProviderManager()
    reloaded_provider = reloaded.get_provider("agentteams-gateway")
    assert reloaded_provider is not None
    model = next(
        m for m in reloaded_provider.extra_models if m.id == "deepseek-v4-pro"
    )
    assert model.supports_image is False
    assert model.supports_multimodal is False
    assert model.probe_source == "documentation"


def test_registry_get_expected_by_model_id_bare_name() -> None:
    """Bare-model lookup finds baseline entries across providers."""
    registry = ExpectedCapabilityRegistry()
    expected = registry.get_expected_by_model_id("qwen3.6-plus")
    assert expected is not None
    assert expected.expected_image is True
    assert expected.expected_video is True

    missing = registry.get_expected_by_model_id("no-such-model-xyz")
    assert missing is None


async def test_annotation_service_bare_name_fallback_toggle(
    isolated_secret_dir,
    monkeypatch,
) -> None:
    """bare_name_fallback is the only knob: off (default, builtin path)
    a custom provider id never hits the bare-name lookup; on, it does."""
    calls: list[tuple[str, str, bool]] = []
    registry = ExpectedCapabilityRegistry()
    real_get_expected = registry.get_expected

    def spy_get_expected(provider_id: str, model_id: str):
        calls.append((provider_id, model_id, False))
        return real_get_expected(provider_id, model_id)

    monkeypatch.setattr(registry, "get_expected", spy_get_expected)
    service = ProviderAnnotationService(registry)
    model = ModelInfo(id="qwen3.6-plus", name="Qwen3.6 Plus")
    provider = OpenAIProvider(id="my-custom", name="My Custom")

    service.annotate_model(provider, model)
    assert model.supports_image is None
    assert all(flag is False for _, _, flag in calls)

    calls.clear()
    model2 = ModelInfo(id="qwen3.6-plus", name="Qwen3.6 Plus")
    service.annotate_model(provider, model2, bare_name_fallback=True)
    assert model2.supports_image is True
    assert model2.probe_source == "documentation"
