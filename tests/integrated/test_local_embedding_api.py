# -*- coding: utf-8 -*-
"""Integration tests for local embedding API endpoints."""

from __future__ import annotations

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestEmbeddingApiEndpoints:
    """Tests for local embedding API endpoints."""

    def test_preset_models_returns_valid_structure(self, running_app):
        """Test that preset-models endpoint returns valid model list."""
        client = running_app
        response = client.get(
            "/api/config/agents/local-embedding/preset-models",
        )

        assert response.status_code == 200
        data = response.json()

        # Check structure
        assert "multimodal" in data
        assert "text" in data
        assert isinstance(data["multimodal"], list)
        assert isinstance(data["text"], list)

        # Check multimodal models
        if data["multimodal"]:
            model = data["multimodal"][0]
            assert "id" in model
            assert "type" in model
            assert "dimensions" in model
            assert model["type"] == "multimodal"

        # Check text models
        if data["text"]:
            model = data["text"][0]
            assert "id" in model
            assert "type" in model
            assert "dimensions" in model
            assert model["type"] == "text"

    def test_get_local_embedding_config(self, running_app):
        """Test getting current local embedding configuration."""
        client = running_app
        response = client.get("/api/config/agents/local-embedding")

        assert response.status_code == 200
        data = response.json()

        # Check required fields exist
        assert "enabled" in data
        assert "model_id" in data
        assert "device" in data
        assert "dtype" in data
        assert "download_source" in data

        # Check value types
        assert isinstance(data["enabled"], bool)
        assert isinstance(data["model_id"], str)
        assert data["dtype"] in ["fp16", "bf16", "fp32"]
        assert data["download_source"] in ["modelscope", "huggingface"]

    def test_update_local_embedding_config(self, running_app):
        """Test updating local embedding configuration."""
        client = running_app

        new_config = {
            "enabled": True,
            "model_id": "BAAI/bge-large-zh-v1.5",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "huggingface",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=new_config,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify updated values
        assert data["enabled"] == new_config["enabled"]
        assert data["model_id"] == new_config["model_id"]
        assert data["device"] == new_config["device"]
        assert data["dtype"] == new_config["dtype"]

    def test_local_embedding_test_endpoint_exists(self, running_app):
        """Test that the test endpoint accepts requests."""
        client = running_app

        test_config = {
            "enabled": True,
            "model_id": "BAAI/bge-small-zh",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "huggingface",
        }

        response = client.post(
            "/api/config/agents/local-embedding/test",
            json=test_config,
        )

        # Accept 200 (success) or 500 (model load failed due to missing model)
        # The important thing is the endpoint exists and responds
        assert response.status_code in [200, 500]

    def test_local_embedding_download_endpoint_exists(self, running_app):
        """Test that the download endpoint accepts requests."""
        client = running_app

        download_config = {
            "enabled": True,
            "model_id": "BAAI/bge-small-zh",
            "download_source": "huggingface",
        }

        response = client.post(
            "/api/config/agents/local-embedding/download",
            json=download_config,
        )

        # Accept 200 (success) or 500 (download failed)
        assert response.status_code in [200, 500]


class TestEmbeddingConfigPersistence:
    """Tests for embedding config persistence across requests."""

    def test_config_persists_after_update(self, running_app):
        """Test that updated config persists for subsequent requests."""
        client = running_app

        # Update config
        new_config = {
            "enabled": True,
            "model_id": "BAAI/bge-m3",
            "device": "auto",
            "dtype": "bf16",
            "download_source": "modelscope",
        }

        update_response = client.put(
            "/api/config/agents/local-embedding",
            json=new_config,
        )
        assert update_response.status_code == 200

        # Get config
        get_response = client.get("/api/config/agents/local-embedding")
        assert get_response.status_code == 200

        data = get_response.json()
        assert data["model_id"] == new_config["model_id"]
        assert data["dtype"] == new_config["dtype"]


class TestEmbeddingApiErrorHandling:
    """Tests for embedding API error handling."""

    def test_invalid_dtype_rejected(self, running_app):
        """Test that invalid dtype values are rejected."""
        client = running_app

        invalid_config = {
            "enabled": True,
            "model_id": "test/model",
            "dtype": "invalid_dtype",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=invalid_config,
        )

        # Should return validation error
        assert response.status_code == 422  # Unprocessable Entity

    def test_invalid_download_source_rejected(self, running_app):
        """Test that invalid download_source values are rejected."""
        client = running_app

        invalid_config = {
            "enabled": True,
            "model_id": "test/model",
            "download_source": "invalid_source",
        }

        response = client.put(
            "/api/config/agents/local-embedding",
            json=invalid_config,
        )

        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
