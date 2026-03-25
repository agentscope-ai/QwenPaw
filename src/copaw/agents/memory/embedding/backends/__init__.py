# -*- coding: utf-8 -*-
"""Embedding backend implementations."""

from .base import EmbeddingBackend
from .transformers_backend import TransformersEmbeddingBackend
from .ollama_backend import OllamaEmbeddingBackend

__all__ = [
    "EmbeddingBackend",
    "TransformersEmbeddingBackend",
    "OllamaEmbeddingBackend",
]
