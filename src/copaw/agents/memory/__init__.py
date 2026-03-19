# -*- coding: utf-8 -*-
"""Memory management module for CoPaw agents."""

from .agent_md_manager import AgentMdManager
from .memory_manager import MemoryManager
from .local_embedder import (
    LocalEmbedder,
    download_model_for_config,
    PRESET_MODELS,
)
from .embedding_adapter import (
    EmbeddingAdapter,
    EmbeddingModeResult,
    RemoteEmbeddingConfig,
    create_embedding_adapter,
)
from .local_embedding_model import LocalEmbeddingModel

__all__ = [
    "AgentMdManager",
    "MemoryManager",
    "LocalEmbedder",
    "download_model_for_config",
    "PRESET_MODELS",
    "EmbeddingAdapter",
    "EmbeddingModeResult",
    "RemoteEmbeddingConfig",
    "create_embedding_adapter",
    "LocalEmbeddingModel",
]
