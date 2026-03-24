# -*- coding: utf-8 -*-
"""ADR-003 ReMe client for the transformers-backed ``local`` registry."""

from copaw.agents.memory.local_embedding_model import LocalEmbeddingModel


class EmbeddingClient(LocalEmbeddingModel):
    """Transformers path registered as ReMe backend name ``local``.

    Subclasses :class:`LocalEmbeddingModel`; behavior is identical. Use this
    symbol when referring to the CoPaw-managed ReMe adapter in architecture
    docs (ADR-003).
    """
