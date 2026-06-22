# -*- coding: utf-8 -*-
"""Runner package exports.

Keep this package initializer lightweight. Importing a submodule such as
``qwenpaw.app.runner.session`` should not eagerly import AgentRunner,
QwenPawAgent, tools, or ACP runtime dependencies.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import router
    from .manager import ChatManager
    from .models import ChatHistory, ChatSpec, ChatsFile
    from .repo import BaseChatRepository, JsonChatRepository
    from .runner import AgentRunner

__all__ = [
    # Core classes
    "AgentRunner",
    "ChatManager",
    # API
    "router",
    # Models
    "ChatSpec",
    "ChatHistory",
    "ChatsFile",
    # Chat Repository
    "BaseChatRepository",
    "JsonChatRepository",
]


def __getattr__(name: str) -> Any:
    """Lazily expose historical package-level exports."""
    if name == "AgentRunner":
        from .runner import AgentRunner

        return AgentRunner
    if name == "router":
        from .api import router

        return router
    if name == "ChatManager":
        from .manager import ChatManager

        return ChatManager
    if name in {"ChatSpec", "ChatHistory", "ChatsFile"}:
        from .models import ChatHistory, ChatSpec, ChatsFile

        return {
            "ChatSpec": ChatSpec,
            "ChatHistory": ChatHistory,
            "ChatsFile": ChatsFile,
        }[name]
    if name in {"BaseChatRepository", "JsonChatRepository"}:
        from .repo import BaseChatRepository, JsonChatRepository

        return {
            "BaseChatRepository": BaseChatRepository,
            "JsonChatRepository": JsonChatRepository,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
