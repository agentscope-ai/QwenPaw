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
    build_reme_embedding_dict_for_running,
    create_embedding_adapter,
    get_reme_embedding_and_vector_enabled,
)
from .local_embedding_model import LocalEmbeddingModel
from .embedding_client import EmbeddingClient
from .ollama_embedding_model import OllamaEmbeddingModel

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
    "get_reme_embedding_and_vector_enabled",
    "build_reme_embedding_dict_for_running",
    "LocalEmbeddingModel",
    "EmbeddingClient",
    "OllamaEmbeddingModel",
]
