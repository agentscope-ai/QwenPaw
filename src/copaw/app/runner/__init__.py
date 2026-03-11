# -*- coding: utf-8 -*-
"""Runner module exports with lazy loading to avoid import cycles."""
# pylint: disable=undefined-all-variable
from __future__ import annotations

from importlib import import_module


__all__ = [
    "AgentRunner",
    "ChatManager",
    "router",
    "ChatSpec",
    "ChatHistory",
    "ChatsFile",
    "BaseChatRepository",
    "JsonChatRepository",
    "SQLiteChatRepository",
]


def __getattr__(name: str):
    if name == "AgentRunner":
        return getattr(import_module(".runner", __name__), name)
    if name == "ChatManager":
        return getattr(import_module(".manager", __name__), name)
    if name == "router":
        return getattr(import_module(".api", __name__), name)
    if name in {"ChatSpec", "ChatHistory", "ChatsFile"}:
        return getattr(import_module(".models", __name__), name)
    if name in {
        "BaseChatRepository",
        "JsonChatRepository",
        "SQLiteChatRepository",
    }:
        return getattr(import_module(".repo", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
