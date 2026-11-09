# -*- coding: utf-8 -*-
"""Local model management and inference."""

from .manager import (
    DEFAULT_LOCAL_ENGINE,
    LOCAL_ENGINE_IDS,
    LocalEngineId,
    LocalModelConfig,
    LocalModelManager,
    LocalServerSetupResult,
    normalize_engine,
)
from .model_manager import ModelManager, LocalModelInfo, DownloadSource
from .llamacpp import LlamaCppBackend
from .mlx import MlxBackend

__all__ = [
    "DEFAULT_LOCAL_ENGINE",
    "DownloadSource",
    "LOCAL_ENGINE_IDS",
    "LlamaCppBackend",
    "LocalEngineId",
    "LocalModelConfig",
    "LocalModelInfo",
    "LocalModelManager",
    "LocalServerSetupResult",
    "MlxBackend",
    "ModelManager",
    "normalize_engine",
]
