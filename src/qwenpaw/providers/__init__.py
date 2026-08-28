# -*- coding: utf-8 -*-
"""Provider management — models, registry + persistent store."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provider import ModelInfo, Provider, ProviderInfo
    from .provider_manager import ProviderManager


_EXPORT_MODULES = {
    "ModelInfo": ".provider",
    "Provider": ".provider",
    "ProviderInfo": ".provider",
    "ProviderManager": ".provider_manager",
}

__all__ = [
    "ModelInfo",
    "Provider",
    "ProviderManager",
    "ProviderInfo",
]


def __getattr__(name: str) -> Any:
    """Load public provider exports only when callers request them."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
