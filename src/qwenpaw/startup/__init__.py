# -*- coding: utf-8 -*-
"""Startup optimization module for QwenPaw.

Provides caching, lazy loading, and parallel initialization utilities
to accelerate application startup, especially on Windows.
"""

from .cache import StartupCache, get_startup_cache
from .lazy_loader import (
    LazyLoader,
    ProgressiveInitializer,
    lazy_property,
    parallel_sync_tasks,
    parallel_tasks,
)

__all__ = [
    "StartupCache",
    "get_startup_cache",
    "LazyLoader",
    "ProgressiveInitializer",
    "lazy_property",
    "parallel_tasks",
    "parallel_sync_tasks",
]
