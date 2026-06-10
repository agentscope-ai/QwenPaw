# -*- coding: utf-8 -*-
"""Unit tests for the OpenCode built-in provider.

After review feedback: OPENCODE_MODELS reduced to 8 intersection models
(Zen ∩ Go), endpoint filtering removed for minimal diff.
"""

from qwenpaw.providers.provider_manager import (
    OPENCODE_MODELS,
    PROVIDER_OPENCODE,
    ProviderManager,
)
from qwenpaw.providers.openai_provider import OpenAIProvider


class TestOpenCodeProvider:
    """Test the OpenCode provider with merged OpenCode Go models."""

    def test_opencode_provider_is_openai_compatible(self):
        """PROVIDER_OPENCODE should be an OpenAIProvider."""
        assert isinstance(PROVIDER_OPENCODE, OpenAIProvider)

    def test_opencode_provider_key_attributes(self):
        """Provider-level attributes should be correctly set."""
        assert PROVIDER_OPENCODE.id == "opencode"
        assert PROVIDER_OPENCODE.api_key_prefix == ""
        assert PROVIDER_OPENCODE.require_api_key is False
        assert PROVIDER_OPENCODE.freeze_url is False
        assert PROVIDER_OPENCODE.base_url == "https://opencode.ai/zen/v1"
        assert (
            PROVIDER_OPENCODE.base_url
            == PROVIDER_OPENCODE.meta["base_url_options"][0]["value"]
        )

    def test_opencode_provider_meta_base_url_options(self):
        """meta should contain two base_url_options for endpoint switching."""
        meta = PROVIDER_OPENCODE.meta
        assert "base_url_options" in meta
        urls = meta["base_url_options"]
        assert len(urls) == 2
        assert urls[0]["label"] == "OpenCode"
        assert urls[0]["value"] == "https://opencode.ai/zen/v1"
        assert urls[1]["label"] == "OpenCode Go"
        assert urls[1]["value"] == "https://opencode.ai/zen/go/v1"

    def test_opencode_models_non_empty_and_unique(self):
        """Models list is non-empty with unique IDs."""
        assert len(OPENCODE_MODELS) > 0
        model_ids = [m.id for m in OPENCODE_MODELS]
        assert len(model_ids) == len(set(model_ids))

    def test_opencode_models_have_required_fields(self):
        """Every model has required fields set."""
        for m in OPENCODE_MODELS:
            assert m.id, "Model must have an id"
            assert m.name, "Model must have a name"
            assert isinstance(m.supports_image, bool)
            assert isinstance(m.supports_video, bool)

    def test_opencode_models_probe_source(self):
        """All models should have probe_source='documentation'."""
        for m in OPENCODE_MODELS:
            assert m.probe_source == "documentation"

    def test_opencode_models_all_free(self):
        """All OpenCode models should be marked as free."""
        assert all(
            m.is_free for m in OPENCODE_MODELS
        ), "All OPENCODE_MODELS should be free"

    def test_opencode_registered_in_provider_manager(self):
        """opencode provider should be registerable via built-in init."""
        mgr = ProviderManager()
        assert PROVIDER_OPENCODE.id in mgr.builtin_providers
        provider = mgr.builtin_providers[PROVIDER_OPENCODE.id]
        assert provider.id == PROVIDER_OPENCODE.id
        assert isinstance(provider, OpenAIProvider)

    def test_get_info_returns_all_models(self):
        """get_info() should return all 8 intersection models."""
        import asyncio

        provider = PROVIDER_OPENCODE.model_copy()
        info = asyncio.run(provider.get_info())
        assert len(info.models) == len(OPENCODE_MODELS)
        model_ids = {m.id for m in info.models}
        assert model_ids == {m.id for m in OPENCODE_MODELS}
