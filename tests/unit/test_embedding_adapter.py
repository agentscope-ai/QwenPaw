# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order
# pylint: disable=protected-access,unused-import
"""Unit tests for embedding adapter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import os  # noqa: E402
import pytest  # noqa: E402

from copaw.agents.memory.embedding_adapter import (  # noqa: E402
    EmbeddingAdapter,
    DEFAULT_EMBEDDING_DIMENSIONS,
    EmbeddingModeResult,
    RemoteEmbeddingConfig,
    create_embedding_adapter,
)
from copaw.config.config import LocalEmbeddingConfig  # noqa: E402


class TestEmbeddingAdapter:
    """Test EmbeddingAdapter functionality."""

    def test_create_adapter(self):
        """Test adapter creation."""
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        assert isinstance(adapter, EmbeddingAdapter)
        assert adapter.local_config == config
        assert adapter.strict_local is False

    def test_determine_mode_disabled(self):
        """Test mode determination when both local and remote unavailable."""
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()

        assert result.mode == "disabled"
        assert result.vector_enabled is False
        assert result.fallback_applied is True
        assert result.fallback_reason is not None

    def test_check_remote_available_no_env(self):
        """Test remote availability check without env vars."""
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        # Ensure env vars are not set
        for key in [
            "EMBEDDING_API_KEY",
            "EMBEDDING_BASE_URL",
            "EMBEDDING_MODEL_NAME",
        ]:
            os.environ.pop(key, None)

        available, reason = adapter._check_remote_available()

        assert available is False
        assert "EMBEDDING_API_KEY" in reason

    def test_get_file_store_config(self):
        """Test file store config generation."""
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        store_config = adapter.get_file_store_config()

        assert "vector_enabled" in store_config
        assert store_config["vector_enabled"] is False

    def test_local_config_uses_preset_dimensions(self):
        """Test local config dimensions are inferred from model presets."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )
        adapter._current_mode = "local"

        embedding_config = adapter.get_reme_embedding_config()

        assert embedding_config["backend"] == "local"
        assert embedding_config["dimensions"] == 512

    def test_local_config_uses_2048_when_model_unknown(self):
        """Test unknown local model falls back to 2048 dimensions."""
        config = LocalEmbeddingConfig(enabled=True, model_id="unknown/model")
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )
        adapter._current_mode = "local"

        embedding_config = adapter.get_reme_embedding_config()

        assert embedding_config["backend"] == "local"
        assert embedding_config["dimensions"] == 2048

    def test_check_remote_available_invalid_dimensions(self, monkeypatch):
        """Test invalid dimensions env falls back to default safely."""
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
        monkeypatch.setenv("EMBEDDING_DIMENSIONS", "invalid-int")

        available, reason = adapter._check_remote_available()

        assert available is True
        assert reason is None
        assert adapter._remote_config is not None
        assert (
            adapter._remote_config.dimensions == DEFAULT_EMBEDDING_DIMENSIONS
        )


class TestEmbeddingModeResult:
    """Test EmbeddingModeResult dataclass."""

    def test_result_creation(self):
        """Test result object creation."""
        result = EmbeddingModeResult(
            mode="local",
            vector_enabled=True,
            backend_config={"backend": "local"},
            fallback_applied=False,
            fallback_reason=None,
        )

        assert result.mode == "local"
        assert result.vector_enabled is True
        assert result.fallback_applied is False


class TestRemoteEmbeddingConfig:
    """Test RemoteEmbeddingConfig dataclass."""

    def test_config_creation(self):
        """Test remote config creation."""
        config = RemoteEmbeddingConfig(
            api_key="test_key",
            base_url="https://api.example.com",
            model_name="test-model",
            dimensions=1024,
        )

        assert config.api_key == "test_key"
        assert config.base_url == "https://api.example.com"
        assert config.model_name == "test-model"
        assert config.dimensions == 1024
