# -*- coding: utf-8 -*-
"""Runner package exports.

Keep imports lazy so submodules like runtime_status_store can be imported
without pulling in runner.py during package initialization.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "AgentRunner",
    "ChatManager",
    "router",
    "ChatSpec",
    "ChatHistory",
    "ChatsFile",
    "BaseChatRepository",
    "JsonChatRepository",
]


def __getattr__(name: str) -> Any:
    if name == "AgentRunner":
        return import_module(".runner", __name__).AgentRunner
    if name == "router":
        return import_module(".api", __name__).router
    if name == "ChatManager":
        return import_module(".manager", __name__).ChatManager
    if name in {"ChatSpec", "ChatHistory", "ChatsFile"}:
        return getattr(import_module(".models", __name__), name)
    if name in {"BaseChatRepository", "JsonChatRepository"}:
        return getattr(import_module(".repo", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
