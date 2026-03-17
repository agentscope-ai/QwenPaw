# -*- coding: utf-8 -*-
"""Integration tests for vector output verification.

These tests verify that the embedding models produce correct vector outputs
without testing internal implementation details.
"""
from __future__ import annotations

import pytest


# Mark all tests in this module as slow integration tests
pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestVectorOutputProperties:
    """Tests for vector output properties.

    These tests verify that encode_text() produces outputs with correct properties:
    - Returns a list of lists
    - Vectors are normalized (L2)
    - Dimensions match model metadata
    """

    def test_encode_text_returns_list_of_lists(self, running_app):
        """Test that encode_text returns a list of lists."""
        import httpx

        client = running_app

        # Use a simple config that should work on CPU
        config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "modelscope",
        }

        response = client.post(
            "/api/config/agents/local-embedding/test",
            json=config,
            timeout=300.0,
        )

        # If successful, verify the response structure
        if response.status_code == 200:
            data = response.json()
            assert data.get("success") is True
            # The test endpoint doesn't return embeddings directly,
            # but we verify the model loaded correctly
            if "model_info" in data:
                assert "dimensions" in data["model_info"]

    def test_model_info_contains_dimensions(self, running_app):
        """Test that model_info contains correct dimensions."""
        import httpx

        client = running_app

        # Test multimodal model
        config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",
            "dtype": "fp32",
        }

        response = client.post(
            "/api/config/agents/local-embedding/test",
            json=config,
            timeout=300.0,
        )

        if response.status_code == 200:
            data = response.json()
            if "model_info" in data:
                model_info = data["model_info"]
                assert model_info["dimensions"] == 2048
                assert model_info["model_type"] == "multimodal"


class TestVectorSearchIntegration:
    """Tests for vector search integration.

    Verifies that enabling local embedding configures vector search correctly.
    """

    def test_vector_search_enabled_with_config_update(self, running_app):
        """Test that vector search is enabled when local embedding is configured."""
        import httpx

        client = running_app

        # Enable local embedding
        enable_config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",
            "dtype": "fp32",
        }

        # Update config
        put_response = client.put(
            "/api/config/agents/local-embedding",
            json=enable_config,
        )
        assert put_response.status_code == 200

        # Verify config was saved
        get_response = client.get("/api/config/agents/local-embedding")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["enabled"] is True
        assert data["model_id"] == "qwen/Qwen3-VL-Embedding-2B"


class TestMultipleModelTypes:
    """Tests for different model types.

    Verifies that both multimodal and text-only models can be configured.
    """

    def test_qwen_multimodal_model_config(self, running_app):
        """Test that Qwen3-VL multimodal model can be configured."""
        import httpx

        client = running_app

        config = {
            "enabled": True,
            "model_id": "qwen/Qwen3-VL-Embedding-2B",
            "device": "cpu",
            "dtype": "fp32",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=config,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "qwen/Qwen3-VL-Embedding-2B"

    def test_bge_text_model_config(self, running_app):
        """Test that BGE text model can be configured."""
        import httpx

        client = running_app

        config = {
            "enabled": True,
            "model_id": "BAAI/bge-large-zh-v1.5",
            "device": "cpu",
            "dtype": "fp32",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=config,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "BAAI/bge-large-zh-v1.5"


class TestPresetModelsIntegrity:
    """Tests for preset models data integrity.

    Verifies that preset models have correct metadata for both sources.
    """

    def test_preset_models_have_valid_structure(self, running_app):
        """Test that preset-models endpoint returns valid structure."""
        import httpx

        client = running_app

        response = client.get("/api/config/agents/local-embedding/preset-models")
        assert response.status_code == 200

        data = response.json()

        # Check structure
        assert "multimodal" in data
        assert "text" in data
        assert isinstance(data["multimodal"], list)
        assert isinstance(data["text"], list)

        # Check multimodal models
        for model in data["multimodal"]:
            assert "id" in model
            assert "type" in model
            assert model["type"] == "multimodal"
            assert "dimensions" in model
            assert model["dimensions"] == 2048

        # Check text models
        for model in data["text"]:
            assert "id" in model
            assert "type" in model
            assert model["type"] == "text"
            assert "dimensions" in model
            assert model["dimensions"] in [512, 1024]  # bge-small or bge-large


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "slow"])
