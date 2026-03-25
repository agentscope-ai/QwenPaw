# -*- coding: utf-8 -*-
"""Transformers embedding backend wrapper."""

from __future__ import annotations

from typing import List

from copaw.agents.memory.embedding.backends.base import EmbeddingBackend
from copaw.agents.memory.local_embedder import LocalEmbedder
from copaw.config.config import LocalEmbeddingConfig


class TransformersEmbeddingBackend(EmbeddingBackend):
    """Embedding backend based on LocalEmbedder (transformers models)."""

    def __init__(self, local_config: LocalEmbeddingConfig) -> None:
        self._embedder = LocalEmbedder(local_config)

    @property
    def dimensions(self) -> int:
        info = self._embedder.get_model_info()
        return int(info.get("dimensions", 0))

    def encode_text(self, texts: List[str]) -> List[List[float]]:
        return self._embedder.encode_text(texts)

    def unload(self) -> None:
        self._embedder.unload()
