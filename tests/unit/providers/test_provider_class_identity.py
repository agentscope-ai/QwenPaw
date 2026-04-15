# -*- coding: utf-8 -*-
"""Tests for ModelInfo class-identity resilience (issues #3301 / #3375).

When the same module is loaded via two different import paths (e.g.
PYTHONPATH=src/ combined with a pip-installed package), Python creates
two distinct class objects for ModelInfo.  Pydantic v2 treats them as
incompatible types, causing ValidationError on ProviderInfo construction
and Provider.update_config().

These tests simulate that scenario by fabricating a "foreign" ModelInfo
class and verifying that Provider.get_info() and update_config() still
succeed.
"""

from __future__ import annotations

import types
from typing import List

import pytest
from pydantic import BaseModel, Field, ValidationError

from qwenpaw.providers.provider import ModelInfo, Provider, ProviderInfo


# ---------------------------------------------------------------------------
# Helpers: create a "foreign" ModelInfo that shares the same schema but is
# a different Python class — exactly what happens under dual module loading.
# ---------------------------------------------------------------------------

_FOREIGN_SRC = """\
from pydantic import BaseModel, Field

class ModelInfo(BaseModel):
    id: str = Field(..., description="Model identifier used in API calls")
    name: str = Field(..., description="Human-readable model name")
    supports_multimodal: bool | None = None
    supports_image: bool | None = None
    supports_video: bool | None = None
    probe_source: str | None = None
    generate_kwargs: dict = Field(default_factory=dict)
"""


def _make_foreign_model_info(model_id: str, name: str):
    """Create a ModelInfo instance whose class is *not* the canonical one."""
    ns: dict = {}
    exec(_FOREIGN_SRC, ns)  # noqa: S102
    ForeignModelInfo = ns["ModelInfo"]

    # Sanity: the two classes must be distinct
    assert ForeignModelInfo is not ModelInfo
    instance = ForeignModelInfo(id=model_id, name=name)
    assert not isinstance(instance, ModelInfo)
    return instance


# ---------------------------------------------------------------------------
# A minimal concrete Provider for testing (Provider is abstract).
# ---------------------------------------------------------------------------

class _StubProvider(Provider):
    async def check_connection(self, timeout=5):
        return True, "ok"

    async def fetch_models(self, timeout=5):
        return []

    async def check_model_connection(self, model_id, timeout=5):
        return True, "ok"

    def get_chat_model_instance(self, model_id):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetInfoClassIdentity:
    """Provider.get_info() must tolerate foreign ModelInfo instances."""

    @pytest.mark.asyncio
    async def test_get_info_with_foreign_models(self):
        """get_info() should not raise even when self.models contains
        ModelInfo instances from a different class identity."""
        foreign = _make_foreign_model_info("qwen-test", "Qwen Test")

        provider = _StubProvider(
            id="test-provider",
            name="Test",
            # Use canonical ModelInfo for construction, then swap
            models=[ModelInfo(id="qwen-test", name="Qwen Test")],
        )
        # Simulate class-identity mismatch by replacing with foreign instance
        provider.models = [foreign]

        # Before the fix this would raise ValidationError
        info = await provider.get_info()
        assert isinstance(info, ProviderInfo)
        assert len(info.models) == 1
        assert info.models[0].id == "qwen-test"
        # The returned ModelInfo must be the canonical class
        assert isinstance(info.models[0], ModelInfo)

    @pytest.mark.asyncio
    async def test_get_info_with_foreign_extra_models(self):
        """get_info() should not raise even when self.extra_models contains
        ModelInfo instances from a different class identity."""
        foreign = _make_foreign_model_info("glm-5", "GLM 5")

        provider = _StubProvider(
            id="test-provider",
            name="Test",
        )
        provider.extra_models = [foreign]

        info = await provider.get_info()
        assert isinstance(info, ProviderInfo)
        assert len(info.extra_models) == 1
        assert info.extra_models[0].id == "glm-5"
        assert isinstance(info.extra_models[0], ModelInfo)


class TestUpdateConfigClassIdentity:
    """Provider.update_config() must tolerate foreign ModelInfo instances."""

    def test_update_config_with_foreign_model_instances(self):
        """update_config() with foreign ModelInfo instances in extra_models
        should succeed by serializing through dicts."""
        foreign = _make_foreign_model_info("qwen3.5-plus", "Qwen 3.5 Plus")

        provider = _StubProvider(id="test-provider", name="Test")
        provider.update_config({"extra_models": [foreign]})

        assert len(provider.extra_models) == 1
        assert provider.extra_models[0].id == "qwen3.5-plus"
        # Must be canonical ModelInfo, not foreign
        assert isinstance(provider.extra_models[0], ModelInfo)

    def test_update_config_with_dict_models(self):
        """update_config() with plain dicts should still work normally."""
        provider = _StubProvider(id="test-provider", name="Test")
        provider.update_config({
            "extra_models": [
                {"id": "model-a", "name": "Model A"},
                {"id": "model-b", "name": "Model B"},
            ]
        })

        assert len(provider.extra_models) == 2
        assert all(isinstance(m, ModelInfo) for m in provider.extra_models)

    def test_update_config_with_canonical_model_instances(self):
        """update_config() with canonical ModelInfo instances must still work."""
        canonical = ModelInfo(id="model-c", name="Model C")

        provider = _StubProvider(id="test-provider", name="Test")
        provider.update_config({"extra_models": [canonical]})

        assert len(provider.extra_models) == 1
        assert provider.extra_models[0].id == "model-c"
        assert isinstance(provider.extra_models[0], ModelInfo)


class TestProviderInfoDirectConstruction:
    """ProviderInfo construction must handle foreign ModelInfo in fields."""

    def test_provider_info_rejects_foreign_model_directly(self):
        """Without the get_info() dict-serialization fix, directly passing
        a foreign ModelInfo to ProviderInfo would fail — confirm that the
        failure mode exists so the fix is meaningful."""
        foreign = _make_foreign_model_info("test-model", "Test")
        with pytest.raises(ValidationError):
            ProviderInfo(
                id="p",
                name="P",
                extra_models=[foreign],
            )

    def test_provider_info_accepts_dicts(self):
        """ProviderInfo must accept plain dicts for models/extra_models."""
        info = ProviderInfo(
            id="p",
            name="P",
            models=[{"id": "m1", "name": "M1"}],
            extra_models=[{"id": "m2", "name": "M2"}],
        )
        assert info.models[0].id == "m1"
        assert info.extra_models[0].id == "m2"
