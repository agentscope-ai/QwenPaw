# -*- coding: utf-8 -*-
"""Unit tests for the OpenCode built-in provider."""

from qwenpaw.providers.provider_manager import (
    OPENCODE_MODELS,
    PROVIDER_OPENCODE,
    ProviderManager,
)
from qwenpaw.providers.openai_provider import OpenAIProvider


class TestOpenCodeProvider:
    """Test the OpenCode provider with merged OpenCode Go models.

    Refactored per maintainer review: OpenCode Go models merged into
    the existing opencode provider via meta.base_url_options.
    """

    def test_opencode_provider_is_openai_compatible(self):
        """PROVIDER_OPENCODE should be an OpenAIProvider."""
        assert isinstance(PROVIDER_OPENCODE, OpenAIProvider)

    def test_opencode_provider_key_attributes(self):
        """Provider-level attributes should be correctly set."""
        assert PROVIDER_OPENCODE.id == "opencode"
        assert PROVIDER_OPENCODE.api_key_prefix == ""
        assert PROVIDER_OPENCODE.require_api_key is False
        assert PROVIDER_OPENCODE.freeze_url is True
        # Default base_url should match the first option in meta
        assert PROVIDER_OPENCODE.base_url == "https://opencode.ai/zen/v1"
        assert (
            PROVIDER_OPENCODE.base_url
            == PROVIDER_OPENCODE.meta["base_url_options"][0]["value"]
        )

    def test_opencode_provider_meta_base_url_options(self):
        """meta should contain two base_url_options."""
        meta = PROVIDER_OPENCODE.meta
        assert "base_url_options" in meta
        urls = meta["base_url_options"]
        assert len(urls) == 2
        assert urls[0]["label"] == "OpenCode"
        assert urls[0]["value"] == "https://opencode.ai/zen/v1"
        assert urls[1]["label"] == "OpenCode Go"
        assert urls[1]["value"] == "https://opencode.ai/zen/go/v1"

    def test_opencode_models_count_and_key_models(self):
        """Merged models: should be >= 12 and <= 14."""
        model_ids = {m.id for m in OPENCODE_MODELS}
        assert len(model_ids) >= 12, f"Expected >= 12, got {len(model_ids)}"
        assert len(model_ids) <= 14, f"Expected <= 14, got {len(model_ids)}"
        # Free models preserved
        assert "big-pickle" in model_ids
        assert "nemotron-3-super-free" in model_ids
        # Go key models (sample across vendors)
        assert "deepseek-v4-flash" in model_ids
        assert "deepseek-v4-pro" in model_ids
        assert "glm-5.1" in model_ids
        assert "kimi-k2.5" in model_ids

    def test_opencode_models_visual_capabilities(self):
        """Check visual model tagging (mimo-v2.5 corrected)."""
        models_by_id = {m.id: m for m in OPENCODE_MODELS}
        # Vision models
        vision_models = {
            "kimi-k2.5",
            "kimi-k2.6",
            "qwen3.6-plus",
            "qwen3.5-plus",
            "mimo-v2.5",
        }
        for mid in vision_models:
            assert models_by_id[
                mid
            ].supports_image, f"{mid} should support image"
            assert models_by_id[
                mid
            ].supports_video, f"{mid} should support video"
        # Non-vision models
        non_vision = {
            "glm-5.1",
            "glm-5",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "mimo-v2.5-pro",
        }
        for mid in non_vision:
            assert not models_by_id[
                mid
            ].supports_image, f"{mid} should NOT support image"
            assert not models_by_id[
                mid
            ].supports_video, f"{mid} should NOT support video"

    def test_opencode_models_no_duplicates(self):
        """Merged models must not have duplicate IDs."""
        model_ids = [m.id for m in OPENCODE_MODELS]
        assert len(model_ids) == len(
            set(model_ids),
        ), "Duplicate model IDs found in OPENCODE_MODELS"

    def test_opencode_models_probe_source_and_free(self):
        """All models should have probe_source='documentation'."""
        for m in OPENCODE_MODELS:
            assert m.probe_source == "documentation"
        free_models = {m.id for m in OPENCODE_MODELS if m.is_free}
        assert "big-pickle" in free_models
        assert "nemotron-3-super-free" in free_models

    def test_opencode_registered_in_provider_manager(self):
        """opencode provider should be registerable via built-in init."""
        mgr = ProviderManager()
        assert PROVIDER_OPENCODE.id in mgr.builtin_providers
        provider = mgr.builtin_providers[PROVIDER_OPENCODE.id]
        assert provider.id == PROVIDER_OPENCODE.id
        assert isinstance(provider, OpenAIProvider)
