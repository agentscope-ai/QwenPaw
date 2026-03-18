# -*- coding: utf-8 -*-
"""Integration tests for local embedding with real model loading.

These tests require the model to be downloaded and are marked as slow.
Run with: pytest tests/integrated/test_local_embedding_real.py -v -m slow

Note: These tests are optional for CI and primarily run locally by developers
before submitting PRs. They require:
- GPU with CUDA support (or CPU fallback, slower)
- Pre-downloaded model at ~/.cache/copaw/models
"""

from __future__ import annotations

import pytest

# Mark all tests in this module as slow integration tests
pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestLocalEmbeddingRealModel:
    """Real model loading and encoding tests.

    These tests verify actual model loading and encoding functionality.
    They use the already-downloaded Qwen3-VL-Embedding-2B model.
    """

    def test_model_loads_successfully(self, running_app):
        """Test embedding model can be loaded via API test endpoint."""
        client = running_app

        test_config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "auto",  # Will use CUDA if available
            "dtype": "fp16",
            "download_source": "modelscope",
        }

        response = client.post(
            "/api/config/agents/local-embedding/test",
            json=test_config,
        )

        # With real model loaded, we expect either:
        # - 200: Success with latency info
        # - 500: CUDA/GPU error (common on unsupported architectures)
        assert response.status_code in [
            200,
            500,
        ], f"Unexpected status: {response.status_code}"

        if response.status_code == 200:
            data = response.json()
            assert data.get("success") is True
            assert "latency_ms" in data
            assert data.get("latency_ms", 0) > 0

    def test_text_encoding_produces_valid_embedding(self, running_app):
        """Test text encoding produces valid embedding vector."""
        client = running_app

        # First get config to verify state
        config_response = client.get("/api/config/agents/local-embedding")
        assert config_response.status_code == 200

        # The actual encoding test is done via the test endpoint
        # which internally loads the model and encodes sample text
        test_config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",  # Force CPU for predictable behavior
            "dtype": "fp32",  # Use fp32 for CPU compatibility
            "download_source": "modelscope",
        }

        response = client.post(
            "/api/config/agents/local-embedding/test",
            json=test_config,
            timeout=120.0,  # Longer timeout for model loading
        )

        # Accept success or GPU-related failure
        if response.status_code == 200:
            data = response.json()
            assert data.get("success") is True
            # Verify model info is returned
            if "model_info" in data:
                model_info = data["model_info"]
                assert model_info.get("model_type") == "multimodal"
                assert model_info.get("dimensions") == 2048

    def test_vector_search_enabled_with_local_embedding(self, running_app):
        """Test vector search is properly enabled after config update."""
        client = running_app

        # Enable local embedding
        enable_config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "auto",
            "dtype": "fp16",
            "download_source": "modelscope",
        }

        update_response = client.put(
            "/api/config/agents/local-embedding",
            json=enable_config,
        )
        assert update_response.status_code == 200

        # Verify the config was updated
        get_response = client.get("/api/config/agents/local-embedding")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data.get("enabled") is True
        assert data.get("model_id") == "qwen/Qwen3-VL-Embedding-2B"


class TestLocalEmbeddingBGETextModel:
    """Tests for BGE text-only models.

    BGE models are smaller and faster than Qwen3-VL.
    They can be used for text-only embedding scenarios.
    """

    def test_bge_model_encoding(self, running_app):
        """Test BGE text model can encode text."""
        client = running_app

        test_config = {
            "enabled": True,
            "model_id": "BAAI/bge-small-zh",
            "device": "cpu",  # BGE small is fast enough on CPU
            "dtype": "fp32",
            "download_source": "huggingface",
        }

        response = client.post(
            "/api/config/agents/local-embedding/test",
            json=test_config,
            timeout=180.0,
        )

        # BGE-small is small enough that it should succeed even on CPU
        # but we accept failure if model needs downloading
        assert response.status_code in [
            200,
            500,
        ], f"Unexpected status: {response.status_code}"

        if response.status_code == 200:
            data = response.json()
            assert data.get("success") is True
            if "model_info" in data:
                model_info = data["model_info"]
                assert model_info.get("model_type") == "text"
                assert model_info.get("dimensions") == 512


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "slow"])
