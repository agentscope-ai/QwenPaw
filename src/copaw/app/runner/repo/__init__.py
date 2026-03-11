# -*- coding: utf-8 -*-
"""Chat repository exports with lazy loading to avoid import cycles."""
# pylint: disable=undefined-all-variable
from __future__ import annotations

from importlib import import_module


__all__ = ["BaseChatRepository", "JsonChatRepository", "SQLiteChatRepository"]


def __getattr__(name: str):
    if name == "BaseChatRepository":
        return getattr(import_module(".base", __name__), name)
    if name == "JsonChatRepository":
        return getattr(import_module(".json_repo", __name__), name)
    if name == "SQLiteChatRepository":
        return getattr(import_module(".sqlite_repo", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
