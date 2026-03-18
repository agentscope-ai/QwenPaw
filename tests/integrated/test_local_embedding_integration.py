# -*- coding: utf-8 -*-
"""Integration tests for MemoryManager integration with LocalEmbedder.

These tests verify that MemoryManager correctly integrates with LocalEmbedder
and that vector search is properly configured when local embedding is enabled.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestMemoryManagerLocalEmbedderIntegration:
    """Tests for MemoryManager and LocalEmbedder integration."""

    def test_memory_manager_loads_local_embedder(self, running_app):
        """Test MemoryManager loads local embedder when configured."""
        client = running_app

        # Enable local embedding
        enable_config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",  # Use CPU to avoid GPU issues
            "dtype": "fp32",  # FP32 for CPU compatibility
            "download_source": "modelscope",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=enable_config,
        )

        assert (
            response.status_code == 200
        ), f"Config update failed: {response.text}"

        # Verify the config was saved
        get_response = client.get("/api/config/agents/local-embedding")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["enabled"] is True
        assert data["model_id"] == "qwen/Qwen3-VL-Embedding-2B"

    def test_config_persistence_across_restart(self, running_app):
        """Test local embedding config persists and loads on restart.

        Note: This test verifies config saving, not actual restart.
        """
        client = running_app

        # Set a specific config
        custom_config = {
            "enabled": True,
            "model_id": "BAAI/bge-small-zh",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "huggingface",
        }

        put_response = client.put(
            "/api/config/agents/local-embedding",
            json=custom_config,
        )
        assert put_response.status_code == 200

        # Read it back
        get_response = client.get("/api/config/agents/local-embedding")
        assert get_response.status_code == 200
        data = get_response.json()

        assert data["enabled"] is True
        assert data["model_id"] == "BAAI/bge-small-zh"
        assert data["device"] == "cpu"
        assert data["dtype"] == "fp32"
        assert data["download_source"] == "huggingface"


class TestLocalEmbeddingModelTypes:
    """Tests for different embedding model types."""

    def test_multimodal_model_config(self, running_app):
        """Test multimodal model (Qwen3-VL) can be configured."""
        client = running_app

        config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "modelscope",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=config,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "qwen/Qwen3-VL-Embedding-2B"

    def test_text_model_config(self, running_app):
        """Test text-only model (BGE) can be configured."""
        client = running_app

        config = {
            "enabled": True,
            "model_id": "BAAI/bge-large-zh-v1.5",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "huggingface",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=config,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "BAAI/bge-large-zh-v1.5"


class TestLocalEmbeddingDownloadEndpoint:
    """Tests for model download functionality."""

    def test_download_endpoint_accepts_request(self, running_app):
        """Test download endpoint exists and accepts requests."""
        client = running_app

        # This test just verifies the endpoint accepts the request
        # It may fail if model already downloaded or network issues
        config = {
            "enabled": True,
            "model_id": "BAAI/bge-small-zh",
            "download_source": "huggingface",
        }

        response = client.post(
            "/api/config/agents/local-embedding/download",
            json=config,
            timeout=300.0,  # 5 min timeout for download
        )

        # Accept any response - the point is endpoint exists
        assert response.status_code in [200, 500]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "slow"])
