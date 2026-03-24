# -*- coding: utf-8 -*-
"""Abstract embedding backend (ADR-003 Track B)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class EmbeddingBackend(ABC):
    """Internal encode surface.

    ReMe integration uses :class:`BaseEmbeddingModel`.
    """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Vector dimensionality."""

    @abstractmethod
    def encode_text(self, texts: List[str]) -> List[List[float]]:
        """Encode texts to embeddings (sync)."""

    def unload(self) -> None:
        """Release heavy resources if applicable."""
