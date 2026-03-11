# -*- coding: utf-8 -*-
"""Cron repository exports with lazy loading to avoid import cycles."""
# pylint: disable=undefined-all-variable
from __future__ import annotations

from importlib import import_module


__all__ = ["BaseJobRepository", "JsonJobRepository", "SQLiteJobRepository"]


def __getattr__(name: str):
    if name == "BaseJobRepository":
        return getattr(import_module(".base", __name__), name)
    if name == "JsonJobRepository":
        return getattr(import_module(".json_repo", __name__), name)
    if name == "SQLiteJobRepository":
        return getattr(import_module(".sqlite_repo", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
