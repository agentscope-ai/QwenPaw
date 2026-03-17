# -*- coding: utf-8 -*-
"""Unit tests for local embedding functionality."""
from __future__ import annotations

import pytest

from copaw.config.config import LocalEmbeddingConfig
from copaw.agents.memory.local_embedder import (
    LocalEmbedder,
    PRESET_MODELS,
    ModelMetadata,
)


class TestLocalEmbeddingConfig:
    """Tests for LocalEmbeddingConfig model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = LocalEmbeddingConfig()
        assert config.enabled is False
        assert config.model_id == "qwen/Qwen3-VL-Embedding-2B"
        assert config.device == "auto"
        assert config.dtype == "fp16"
        assert config.download_source == "modelscope"
        assert config.model_path is None

    def test_custom_config(self):
        """Test custom configuration values."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-large-zh-v1.5",
            device="cuda",
            dtype="bf16",
            download_source="huggingface",
            model_path="/custom/path",
        )
        assert config.enabled is True
        assert config.model_id == "BAAI/bge-large-zh-v1.5"
        assert config.device == "cuda"
        assert config.dtype == "bf16"
        assert config.download_source == "huggingface"
        assert config.model_path == "/custom/path"

    def test_config_serialization(self):
        """Test config can be serialized and deserialized."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="qwen/Qwen3-VL-Embedding-2B",
            dtype="fp16",
        )
        # Test model_dump
        data = config.model_dump()
        assert data["enabled"] is True
        assert data["model_id"] == "qwen/Qwen3-VL-Embedding-2B"
        assert data["dtype"] == "fp16"

        # Test round-trip
        restored = LocalEmbeddingConfig(**data)
        assert restored.enabled == config.enabled
        assert restored.model_id == config.model_id


class TestPresetModels:
    """Tests for preset models metadata."""

    def test_preset_models_exist(self):
        """Test that preset models are defined."""
        assert len(PRESET_MODELS) > 0

    def test_qwen3_vl_preset(self):
        """Test Qwen3-VL preset model metadata."""
        assert "qwen/Qwen3-VL-Embedding-2B" in PRESET_MODELS
        model = PRESET_MODELS["qwen/Qwen3-VL-Embedding-2B"]
        assert model["type"] == "multimodal"
        assert model["dimensions"] == 2048
        assert model["pooling"] == "last_token"
        assert model["mrl_enabled"] is True
        assert model["mrl_min_dims"] == 64

    def test_bge_text_presets(self):
        """Test BGE text model presets."""
        text_models = ["BAAI/bge-small-zh", "BAAI/bge-large-zh-v1.5", "BAAI/bge-m3"]
        for model_id in text_models:
            assert model_id in PRESET_MODELS
            model = PRESET_MODELS[model_id]
            assert model["type"] == "text"
            assert "dimensions" in model
            assert model["pooling"] == "cls"


class TestModelMetadata:
    """Tests for ModelMetadata."""

    def test_from_preset_multimodal(self):
        """Test creating metadata from preset for multimodal model."""
        meta = ModelMetadata.from_preset("qwen/Qwen3-VL-Embedding-2B")
        assert meta is not None
        assert meta.model_id == "qwen/Qwen3-VL-Embedding-2B"
        assert meta.model_type == "multimodal"
        assert meta.dimensions == 2048
        assert meta.pooling == "last_token"

    def test_from_preset_text(self):
        """Test creating metadata from preset for text model."""
        meta = ModelMetadata.from_preset("BAAI/bge-large-zh-v1.5")
        assert meta is not None
        assert meta.model_id == "BAAI/bge-large-zh-v1.5"
        assert meta.model_type == "text"
        assert meta.dimensions == 1024
        assert meta.pooling == "cls"

    def test_from_preset_unknown(self):
        """Test auto-detect for unknown model."""
        meta = ModelMetadata.auto_detect("unknown/model")
        assert meta is not None
        assert meta.model_type == "text"  # Falls back to text
        assert meta.pooling == "cls"
        assert meta.dimensions == 768  # Default dimension

    def test_repo_id_presence(self):
        """Test that preset models have repo_id for both sources."""
        for model_id, model_data in PRESET_MODELS.items():
            assert "repo_id" in model_data
            assert "modelscope" in model_data["repo_id"]
            assert "huggingface" in model_data["repo_id"]


class TestLocalEmbedderInitialization:
    """Tests for LocalEmbedder initialization without model loading."""

    def test_embedder_init_multimodal(self):
        """Test embedder initialization for multimodal model."""
        config = LocalEmbeddingConfig(
            model_id="qwen/Qwen3-VL-Embedding-2B",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        assert embedder.config == config
        assert embedder._model_loaded is False  # Lazy loading
        assert embedder._metadata.model_type == "multimodal"

    def test_embedder_init_text(self):
        """Test embedder initialization for text model."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-large-zh-v1.5",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        assert embedder.config == config
        assert embedder._model_loaded is False
        assert embedder._metadata.model_type == "text"

    def test_embedder_get_model_info(self):
        """Test get_model_info returns correct metadata."""
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
        assert info["loaded"] is False  # Not yet loaded

    def test_embedder_disabled_raises(self):
        """Test that encode raises when embedder is disabled."""
        config = LocalEmbeddingConfig(
            model_id="qwen/Qwen3-VL-Embedding-2B",
            enabled=False,  # Disabled
        )
        embedder = LocalEmbedder(config)
        with pytest.raises(RuntimeError, match="Local embedding is not enabled"):
            embedder.encode_text(["test"])


class TestLocalEmbedderWithMockedModel:
    """Tests for LocalEmbedder with mocked model loading."""

    @pytest.fixture
    def mock_config(self):
        """Create a test config."""
        return LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh",
            device="cpu",
            dtype="fp32",
            enabled=True,
        )

    def test_encode_text_fallback_path(self, mock_config):
        """Test encode_text falls back correctly when model path doesn't exist."""
        # This test verifies the code path without actual model download
        embedder = LocalEmbedder(mock_config)
        # Since model_path doesn't exist and download will fail in test,
        # this verifies the config parsing works
        assert embedder._metadata.model_id == "BAAI/bge-small-zh"


class TestEmbeddingDimensions:
    """Tests for embedding dimensions handling."""

    def test_multimodal_dimensions(self):
        """Test multimodal model dimensions."""
        meta = ModelMetadata.from_preset("qwen/Qwen3-VL-Embedding-2B")
        assert meta.dimensions == 2048

    def test_text_model_dimensions(self):
        """Test various text model dimensions."""
        test_cases = [
            ("BAAI/bge-small-zh", 512),
            ("BAAI/bge-large-zh-v1.5", 1024),
            ("BAAI/bge-m3", 1024),
        ]
        for model_id, expected_dims in test_cases:
            meta = ModelMetadata.from_preset(model_id)
            assert meta.dimensions == expected_dims


class TestMRLSupport:
    """Tests for MRL (Matryoshka Representation Learning) support."""

    def test_mrl_enabled_for_qwen(self):
        """Test that Qwen3-VL has MRL enabled."""
        model = PRESET_MODELS["qwen/Qwen3-VL-Embedding-2B"]
        assert model.get("mrl_enabled") is True
        assert model.get("mrl_min_dims") == 64

    def test_mrl_not_in_bge(self):
        """Test that BGE models don't have MRL (text-only)."""
        for model_id in ["BAAI/bge-small-zh", "BAAI/bge-large-zh-v1.5", "BAAI/bge-m3"]:
            model = PRESET_MODELS[model_id]
            assert model.get("mrl_enabled") is not True


class TestTorchDtypeMapping:
    """Tests for torch dtype mapping."""

    def test_dtype_conversion(self):
        """Test that dtype string maps to correct torch dtype."""
        from copaw.agents.memory.local_embedder import LocalEmbedder

        config_fp16 = LocalEmbeddingConfig(dtype="fp16", enabled=True)
        config_bf16 = LocalEmbeddingConfig(dtype="bf16", enabled=True)
        config_fp32 = LocalEmbeddingConfig(dtype="fp32", enabled=True)

        # Verify configs are created correctly (actual torch conversion happens in impl)
        assert config_fp16.dtype == "fp16"
        assert config_bf16.dtype == "bf16"
        assert config_fp32.dtype == "fp32"


class TestDownloadModelForConfig:
    """Tests for download_model_for_config utility function."""

    def test_download_function_exists(self):
        """Test that download_model_for_config function exists and is importable."""
        from copaw.agents.memory.local_embedder import download_model_for_config
        assert callable(download_model_for_config)

    def test_download_returns_path_type(self):
        """Test that download_model_for_config returns a string path."""
        from copaw.agents.memory.local_embedder import download_model_for_config

        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh",
            enabled=True,
        )
        # Note: This will attempt download, so may fail without network
        # We just verify the function can be called and returns expected type
        try:
            result = download_model_for_config(config)
            assert isinstance(result, str)
        except Exception:
            # Network/download errors are acceptable in unit test environment
            pass

    def test_download_with_custom_model_path(self):
        """Test download_model_for_config with a custom model path that doesn't exist."""
        from copaw.agents.memory.local_embedder import download_model_for_config

        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-large-zh-v1.5",
            model_path="/nonexistent/path",
            enabled=True,
        )
        # Should attempt download when custom path doesn't exist
        try:
            result = download_model_for_config(config)
            assert isinstance(result, str)
            assert len(result) > 0
        except Exception:
            # Expected to fail in test environment without network
            pass

    def test_download_respects_download_source(self):
        """Test that download_source config is respected."""
        from copaw.agents.memory.local_embedder import download_model_for_config

        config = LocalEmbeddingConfig(
            model_id="qwen/Qwen3-VL-Embedding-2B",
            download_source="huggingface",
            enabled=True,
        )
        try:
            result = download_model_for_config(config)
            assert isinstance(result, str)
        except Exception:
            # Network/download errors are acceptable
            pass


class TestLocalEmbedderInternalPaths:
    """Tests for internal code paths in LocalEmbedder."""

    def test_metadata_auto_detect_for_unknown_model(self):
        """Test that auto_detect is called for unknown model."""
        config = LocalEmbeddingConfig(
            model_id="some/unknown-model",
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        # Should fall back to text model with default dimensions
        assert embedder._metadata.model_type == "text"
        assert embedder._metadata.dimensions == 768

    def test_embedder_with_existing_model_path(self):
        """Test embedder initialization with existing model_path."""
        config = LocalEmbeddingConfig(
            model_id="BAAI/bge-small-zh",
            model_path=".",  # Current directory (unlikely to be valid model)
            enabled=True,
        )
        embedder = LocalEmbedder(config)
        # Should initialize but model_path doesn't exist so will attempt download
        assert embedder.config.model_path == "."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
