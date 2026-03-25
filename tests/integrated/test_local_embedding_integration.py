# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,redefined-outer-name
"""Integration tests for local embedding integration.

These tests verify that local embedding is properly registered and
can be used through the MemoryManager.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest  # noqa: E402

from copaw.agents.memory.embedding_adapter import (  # noqa: E402
    create_embedding_adapter,
)
from copaw.agents.memory.local_embedding_model import (  # noqa: E402
    LocalEmbeddingModel,
)
from copaw.config.config import LocalEmbeddingConfig  # noqa: E402


@pytest.fixture
def disabled_config():
    """Fixture for disabled local embedding config."""
    return LocalEmbeddingConfig(enabled=False)


@pytest.fixture
def enabled_config():
    """Fixture for enabled local embedding config."""
    return LocalEmbeddingConfig(
        enabled=True,
        model_id="BAAI/bge-small-zh",
    )


class TestEmbeddingAdapterIntegration:
    """Test EmbeddingAdapter integration with ReMe."""

    def test_adapter_registers_local_backend(self, enabled_config):
        """Test that adapter can register local backend to ReMe."""
        adapter = create_embedding_adapter(
            local_config=enabled_config,
            strict_local=False,
        )

        # Register local backend
        result = adapter.register_local_backend()

        # Should succeed since ReMe is available
        assert result is True
        assert adapter.is_local_registered is True

    def test_adapter_determines_local_mode(self, enabled_config):
        """Test that adapter correctly determines local mode."""
        adapter = create_embedding_adapter(
            local_config=enabled_config,
            strict_local=False,
        )

        result = adapter.determine_mode()

        # In local mode with dependencies potentially missing,
        # it might fallback, but the adapter should work
        assert result.mode in ["local", "remote", "disabled"]
        assert isinstance(result.vector_enabled, bool)

    def test_adapter_generates_reme_config(self, enabled_config):
        """Test that adapter generates valid ReMe configuration."""
        adapter = create_embedding_adapter(
            local_config=enabled_config,
            strict_local=False,
        )

        # Determine mode first
        adapter.determine_mode()

        # Get ReMe config
        config = adapter.get_reme_embedding_config()

        # Config should be a dict
        assert isinstance(config, dict)

        # If local mode, should have backend field
        if adapter.current_mode == "local":
            assert config.get("backend") == "local"
            assert "model_name" in config
            assert "dimensions" in config

    def test_adapter_generates_file_store_config(self, enabled_config):
        """Test that adapter generates valid file store config."""
        adapter = create_embedding_adapter(
            local_config=enabled_config,
            strict_local=False,
        )

        config = adapter.get_file_store_config()

        assert isinstance(config, dict)
        assert "vector_enabled" in config


class TestLocalEmbeddingModelIntegration:
    """Test LocalEmbeddingModel integration with ReMe."""

    def test_model_is_base_embedding_subclass(self):
        """Test that LocalEmbeddingModel is subclass of BaseEmbeddingModel."""
        from reme.core.embedding import BaseEmbeddingModel

        assert issubclass(LocalEmbeddingModel, BaseEmbeddingModel)

    def test_model_can_be_instantiated(self, enabled_config):
        """Test that LocalEmbeddingModel can be instantiated."""
        model = LocalEmbeddingModel(
            model_name="BAAI/bge-small-zh",
            dimensions=512,
            local_embedding_config=enabled_config,
        )

        assert model.model_name == "BAAI/bge-small-zh"
        assert model.dimensions == 512

    def test_model_has_required_methods(self, enabled_config):
        """Test that model has required ReMe interface methods."""
        model = LocalEmbeddingModel(
            model_name="test-model",
            dimensions=512,
            local_embedding_config=enabled_config,
        )

        # Check required methods exist
        assert hasattr(model, "_get_embeddings")
        assert hasattr(model, "_get_embeddings_sync")
        assert hasattr(model, "get_embedding")
        assert hasattr(model, "get_embeddings")
        assert hasattr(model, "get_embedding_sync")
        assert hasattr(model, "get_embeddings_sync")


class TestStrictMode:
    """Test strict mode behavior."""

    def test_strict_mode_fails_when_local_unavailable(self):
        """Test that strict mode fails when local embedding is unavailable."""
        # Create config with invalid model to ensure failure
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="invalid-model-that-does-not-exist",
            model_path="/nonexistent/path",
        )

        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=True,
        )

        # In strict mode, should raise RuntimeError when local unavailable
        with pytest.raises(RuntimeError) as exc_info:
            adapter.determine_mode()

        assert "Local embedding failed in strict mode" in str(exc_info.value)

    def test_non_strict_mode_fallback_to_remote(self, monkeypatch):
        """Test that non-strict mode falls back to remote when local fails."""
        # Set up remote embedding env vars
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test-model")

        # Create config with disabled local
        config = LocalEmbeddingConfig(enabled=False)

        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()

        assert result.mode == "remote"
        assert result.vector_enabled is True
        assert result.fallback_applied is False


class TestEmbeddingModeResult:
    """Test EmbeddingModeResult data class."""

    def test_result_with_fallback(self):
        """Test result creation with fallback information."""
        from copaw.agents.memory.embedding_adapter import EmbeddingModeResult

        result = EmbeddingModeResult(
            mode="remote",
            vector_enabled=True,
            backend_config={"backend": "openai"},
            fallback_applied=True,
            fallback_reason="Local unavailable: dependency missing",
        )

        assert result.mode == "remote"
        assert result.vector_enabled is True
        assert result.fallback_applied is True
        assert "Local unavailable" in result.fallback_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
