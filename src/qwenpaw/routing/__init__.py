# -*- coding: utf-8 -*-
"""Semantic skill routing module.

Provides optional embedding-based skill retrieval and filtering.
Supports two backends:
1. API mode — uses QwenPaw's EmbeddingConfig (zero extra deps)
2. Local mode — requires sentence-transformers

When neither backend is available and the feature is enabled,
QwenPaw falls back to its original skill selection logic.
"""

# Check if local deps are available
_LOCAL_AVAILABLE = False
try:
    import sentence_transformers  # noqa: F401

    _LOCAL_AVAILABLE = True
except ImportError:
    pass


def is_routing_available() -> bool:
    """Check if any embedding backend is available.

    Returns True if either:
    - QwenPaw's EmbeddingConfig has API configured, OR
    - sentence-transformers is installed (local mode)
    """
    if _LOCAL_AVAILABLE:
        return True
    # Check API availability
    try:
        from .index import _get_embedding_config

        if _get_embedding_config() is not None:
            return True
    except Exception:
        pass
    return False


def __getattr__(name: str):
    """Lazy import for public API.

    Allows ``from qwenpaw.routing import SkillRouter`` etc.
    without loading heavy dependencies at module import time.
    Internal code uses direct sub-module imports instead.
    """
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
