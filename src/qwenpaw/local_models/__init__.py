# -*- coding: utf-8 -*-
"""Local model management and inference."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .llamacpp import LlamaCppBackend
    from .manager import LocalModelConfig, LocalModelManager
    from .model_manager import DownloadSource, LocalModelInfo, ModelManager


_EXPORT_MODULES = {
    "DownloadSource": ".model_manager",
    "LlamaCppBackend": ".llamacpp",
    "LocalModelConfig": ".manager",
    "LocalModelInfo": ".model_manager",
    "LocalModelManager": ".manager",
    "ModelManager": ".model_manager",
}

__all__ = [
    "DownloadSource",
    "LocalModelInfo",
    "LocalModelConfig",
    "LocalModelManager",
    "ModelManager",
    "LlamaCppBackend",
]


def __getattr__(name: str) -> Any:
    """Load public local-model exports only when callers request them."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
