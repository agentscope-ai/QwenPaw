# -*- coding: utf-8 -*-
# src/qwenpaw/pawapp/__init__.py
"""PawApp SDK v2 — Thin wrapper over the QwenPaw Plugin system.

PawApp = a Plugin that has both frontend + backend entries and declares
``meta.pawapp`` fields in its manifest. The SDK provides:

- ``PawApp`` class (wraps PluginApi, exposes decorators)
- ``get_ctx`` (FastAPI dependency injection → PawAppContext)
- ``PawAppContext`` (ctx.chat / ctx.storage / ctx.tools / ctx.ui / etc.)
"""

from .app import PawApp
from .agent import ManagedAgentProfile, ManagedAgentProfileSpec
from .context import PawAppContext
from .dependency import (
    DependencyError,
    DependencyHealth,
    DependencyLifecycle,
    DependencyProbe,
    DependencyRegistry,
    DependencySpec,
)
from .deps import get_ctx, get_scoped_ctx
from .service import ManagedService, ManagedServiceSpec

__all__ = [
    "ManagedService",
    "ManagedServiceSpec",
    "ManagedAgentProfile",
    "ManagedAgentProfileSpec",
    "DependencyError",
    "DependencyHealth",
    "DependencyLifecycle",
    "DependencyProbe",
    "DependencyRegistry",
    "DependencySpec",
    "PawApp",
    "PawAppContext",
    "get_ctx",
    "get_scoped_ctx",
]
