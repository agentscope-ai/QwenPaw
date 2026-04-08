# -*- coding: utf-8 -*-
"""Semantic skill routing module.

Provides optional embedding-based skill retrieval and filtering.
All functionality is disabled by default and requires optional
dependencies (sentence-transformers, faiss-cpu).

When dependencies are not installed, CoPaw falls back to its
original skill selection logic with zero impact.
"""

import logging

logger = logging.getLogger(__name__)

_AVAILABLE = False
try:
    import sentence_transformers  # noqa: F401
    import faiss  # noqa: F401

    _AVAILABLE = True
except ImportError:
    pass


def is_routing_available() -> bool:
    """Check if semantic routing dependencies are installed."""
    return _AVAILABLE


# Lazy public API — only import when actually used
__all__ = [
    "is_routing_available",
    "SemanticRoutingConfig",
    "IndexItem",
    "SearchHit",
    "RoutingResult",
    "SemanticIndex",
    "SkillRouter",
]


def __getattr__(name: str):
    """Lazy import to avoid loading heavy deps at module import time."""
    if name == "SemanticRoutingConfig":
        from .config import SemanticRoutingConfig

        return SemanticRoutingConfig
    if name in ("IndexItem", "SearchHit", "RoutingResult"):
        from . import models

        return getattr(models, name)
    if name == "SemanticIndex":
        from .index import SemanticIndex

        return SemanticIndex
    if name == "SkillRouter":
        from .router import SkillRouter

        return SkillRouter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
