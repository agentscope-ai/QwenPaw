# -*- coding: utf-8 -*-
"""Unit tests for LocalEmbedder public API contract.

These tests verify the public API of LocalEmbedder without testing
internal implementation. Only tests the public contract:
encode(), encode_text(), get_model_info().
"""

from __future__ import annotations

import pytest

from copaw.config.config import LocalEmbeddingConfig
from copaw.agents.memory.local_embedder import LocalEmbedder


class TestLocalEmbedderPublicAPI:
    """Tests for LocalEmbedder public API contract."""

    # pylint: disable=protected-access

    def test_embedder_initialization(self):
        """Test that LocalEmbedder can be initialized with config."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        assert embedder.config == config
        assert embedder._model_loaded is False  # Lazy loading

    def test_get_model_info_returns_dict(self):
        """Test that get_model_info returns a dictionary."""
        config = LocalEmbeddingConfig(
            model_id="qwen/Qwen3-VL-Embedding-2B",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        info = embedder.get_model_info()

        assert isinstance(info, dict)
        assert "model_id" in info
        assert "model_type" in info
        assert "dimensions" in info
        assert "device" in info
        assert "dtype" in info
        assert "loaded" in info

    def test_get_model_info_contains_correct_values(self):
        """Test that get_model_info returns correct metadata."""
        config = LocalEmbeddingConfig(
            model_id="qwen/Qwen3-VL-Embedding-2B",
            device="auto",
            dtype="fp16",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        info = embedder.get_model_info()

        assert info["model_id"] == "qwen/Qwen3-VL-Embedding-2B"
        assert info["model_type"] == "multimodal"
        assert info["dimensions"] == 2048
        assert info["device"] == "auto"
        assert info["dtype"] == "fp16"
        assert info["loaded"] is False  # Not loaded yet

    def test_get_model_info_for_text_model(self):
        """Test get_model_info for text-only model."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-large-zh-v1.5",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        info = embedder.get_model_info()

        assert info["model_id"] == "BAAI/bge-large-zh-v1.5"
        assert info["model_type"] == "text"
        assert info["dimensions"] == 1024


class TestLocalEmbedderEncodeContract:
    """Tests for encode() and encode_text() method contracts."""

    def test_encode_text_method_exists(self):
        """Test that encode_text method exists on embedder."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh", enabled=True
        )
        embedder = LocalEmbedder(config)
        assert hasattr(embedder, "encode_text")
        assert callable(embedder.encode_text)

    def test_encode_text_raises_when_disabled(self):
        """Test encode_text raises RuntimeError when embedder disabled."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh",
            enabled=False,  # Disabled
        )
        embedder = LocalEmbedder(config)

        with pytest.raises(RuntimeError, match="not enabled"):
            embedder.encode_text(["test sentence"])

    def test_encode_text_raises_with_correct_message(self):
        """Test that RuntimeError has correct message."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh", enabled=False
        )
        embedder = LocalEmbedder(config)

        with pytest.raises(RuntimeError) as exc_info:
            embedder.encode_text(["test"])

        assert "not enabled" in str(exc_info.value)


class TestLocalEmbedderMetadataContract:
    """Tests for model metadata handling."""

    def test_metadata_from_preset_multimodal(self):
        """Test that preset multimodal model has correct metadata."""
        from copaw.agents.memory.local_embedder import ModelMetadata

        meta = ModelMetadata.from_preset("qwen/Qwen3-VL-Embedding-2B")
        assert meta is not None
        assert meta.model_type == "multimodal"
        assert meta.dimensions == 2048
        assert meta.pooling == "last_token"

    def test_metadata_from_preset_text(self):
        """Test that preset text model has correct metadata."""
        from copaw.agents.memory.local_embedder import ModelMetadata

        meta = ModelMetadata.from_preset("BAAI/bge-large-zh-v1.5")
        assert meta is not None
        assert meta.model_type == "text"
        assert meta.dimensions == 1024
        assert meta.pooling == "cls"

    def test_metadata_auto_detect_unknown_model(self):
        """Test auto-detect for unknown model."""
        from copaw.agents.memory.local_embedder import ModelMetadata

        meta = ModelMetadata.auto_detect("unknown/model")
        assert meta is not None
        assert meta.model_type == "text"  # Falls back to text
        assert meta.pooling == "cls"
        assert meta.dimensions == 768  # Default dimension


class TestPresetModelsContract:
    """Tests for PRESET_MODELS contract."""

    def test_preset_models_has_required_fields(self):
        """Test that preset models have all required fields."""
        from copaw.agents.memory.local_embedder import PRESET_MODELS

        for _model_id, model_data in PRESET_MODELS.items():
            assert "type" in model_data
            assert "dimensions" in model_data
            assert "pooling" in model_data
            assert "repo_id" in model_data
            assert model_data["type"] in ["multimodal", "text"]

    def test_preset_models_repo_id_has_both_sources(self):
        """Test preset models have ModelScope and HuggingFace repo IDs."""
        from copaw.agents.memory.local_embedder import PRESET_MODELS

        for _model_id, model_data in PRESET_MODELS.items():
            repo_id = model_data["repo_id"]
            assert "modelscope" in repo_id
            assert "huggingface" in repo_id


class TestLocalEmbeddingConfigContract:
    """Tests for LocalEmbeddingConfig contract."""

    def test_config_default_values(self):
        """Test default configuration values."""
        config = LocalEmbeddingConfig()

        assert config.enabled is False
        assert config.model_id == "qwen/Qwen3-VL-Embedding-2B"
        assert config.model_path is None
        assert config.device == "auto"
        assert config.dtype == "fp16"
        assert config.download_source == "modelscope"

    def test_config_dtype_values(self):
        """Test that dtype accepts only valid values."""
        for dtype in ["fp16", "bf16", "fp32"]:
            config = LocalEmbeddingConfig(dtype=dtype)
            assert config.dtype == dtype

    def test_config_download_source_values(self):
        """Test that download_source accepts only valid values."""
        for source in ["modelscope", "huggingface"]:
            config = LocalEmbeddingConfig(download_source=source)
            assert config.download_source == source

    def test_config_serialization_roundtrip(self):
        """Test that config can be serialized and restored."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-large-zh-v1.5",
            device="cuda",
            dtype="bf16",
            download_source="huggingface",
        )

        # Serialize
        data = config.model_dump()

        # Restore
        restored = LocalEmbeddingConfig(**data)

        assert restored.enabled == config.enabled
        assert restored.model_id == config.model_id
        assert restored.device == config.device
        assert restored.dtype == config.dtype
        assert restored.download_source == config.download_source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
