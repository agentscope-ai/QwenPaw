# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order
# -*- coding: utf-8 -*-
"""Unit tests for LocalEmbeddingModel."""

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from copaw.agents.memory.local_embedding_model import (
    LocalEmbeddingModel,
)  # noqa: E402
from copaw.config.config import LocalEmbeddingConfig  # noqa: E402


class TestLocalEmbeddingModel:
    """Test LocalEmbeddingModel functionality."""

    def test_model_creation_with_config(self):
        """Test model creation with explicit config."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )

        model = LocalEmbeddingModel(
            model_name="BAAI/bge-small-zh",
            dimensions=512,
            local_embedding_config=config,
        )

        assert model.model_name == "BAAI/bge-small-zh"
        assert model.dimensions == 512
        assert model._local_config == config

    def test_model_creation_without_config(self):
        """Test model creation without explicit config."""
        model = LocalEmbeddingModel(
            model_name="test-model",
            dimensions=1024,
        )

        assert model.model_name == "test-model"
        assert model.dimensions == 1024
        assert model._local_config is not None
        assert model._local_config.enabled is True

    def test_model_properties(self):
        """Test model properties are set correctly."""
        model = LocalEmbeddingModel(
            model_name="test-model",
            dimensions=768,
            max_batch_size=20,
            max_retries=5,
        )

        assert model.max_batch_size == 20
        assert model.max_retries == 5
        assert model.raise_exception is True

    def test_validate_and_adjust_embedding(self):
        """Test embedding dimension validation."""
        model = LocalEmbeddingModel(
            model_name="test-model",
            dimensions=512,
        )

        # Test correct dimensions
        embedding = [0.1] * 512
        result = model._validate_and_adjust_embedding(embedding)
        assert len(result) == 512

        # Test padding (shorter)
        short_embedding = [0.1] * 300
        result = model._validate_and_adjust_embedding(short_embedding)
        assert len(result) == 512

        # Test truncation (longer)
        long_embedding = [0.1] * 600
        result = model._validate_and_adjust_embedding(long_embedding)
        assert len(result) == 512
