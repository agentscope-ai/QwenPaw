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
        assert PROVIDER_OPENCODE.require_api_key is True
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

    def test_opencode_models_count_and_key_models(self):
        """8 intersection models (Zen ∩ Go)."""
        model_ids = {m.id for m in OPENCODE_MODELS}
        assert len(model_ids) == 8, f"Expected 8, got {len(model_ids)}"
        intersection = {
            "glm-5.1",
            "glm-5",
            "kimi-k2.5",
            "kimi-k2.6",
            "minimax-m2.5",
            "minimax-m2.7",
            "qwen3.6-plus",
            "qwen3.5-plus",
        }
        assert model_ids == intersection
        # Removed models should NOT appear
        assert "big-pickle" not in model_ids
        assert "nemotron-3-super-free" not in model_ids
        assert "deepseek-v4-flash" not in model_ids
        assert "deepseek-v4-pro" not in model_ids
        assert "mimo-v2.5" not in model_ids
        assert "mimo-v2.5-pro" not in model_ids

    def test_opencode_models_visual_capabilities(self):
        """Check visual model tagging."""
        models_by_id = {m.id: m for m in OPENCODE_MODELS}
        # Vision models
        vision_models = {
            "kimi-k2.5",
            "kimi-k2.6",
            "qwen3.6-plus",
            "qwen3.5-plus",
        }
        for mid in vision_models:
            assert models_by_id[
                mid
            ].supports_image, f"{mid} should support image"
            assert models_by_id[
                mid
            ].supports_video, f"{mid} should support video"
        # Non-vision models
        non_vision = {"glm-5.1", "glm-5", "minimax-m2.5", "minimax-m2.7"}
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
        ), "Duplicate model IDs found"

    def test_opencode_models_probe_source(self):
        """All models should have probe_source='documentation'."""
        for m in OPENCODE_MODELS:
            assert m.probe_source == "documentation"

    def test_opencode_models_no_free_models(self):
        """No free models after removing Zen-only big-pickle/nemotron."""
        assert not any(
            m.is_free for m in OPENCODE_MODELS
        ), "OPENCODE_MODELS should not contain free models"

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
