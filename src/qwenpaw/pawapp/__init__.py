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
from .context import PawAppContext
from .deps import get_ctx

__all__ = ["PawApp", "PawAppContext", "get_ctx"]
