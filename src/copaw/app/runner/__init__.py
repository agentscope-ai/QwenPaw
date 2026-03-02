# -*- coding: utf-8 -*-
"""Runner module with chat manager for coordinating repository."""
from __future__ import annotations

from importlib import import_module

# Provide a static symbol for linters/importers, while keeping runtime
# tolerant in lightweight environments that do not install all deps.
try:  # pragma: no cover
    AgentRunner = getattr(import_module(".runner", __name__), "AgentRunner")
except Exception:  # pragma: no cover
    AgentRunner = None

# pylint: disable=undefined-all-variable
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


def __getattr__(name: str):
    """Lazy-load runner exports to avoid importing heavy dependencies."""
    if name == "AgentRunner" and AgentRunner is not None:
        return AgentRunner

    export_map = {
        "AgentRunner": ("runner", "AgentRunner"),
        "router": ("api", "router"),
        "ChatManager": ("manager", "ChatManager"),
        "ChatSpec": ("models", "ChatSpec"),
        "ChatHistory": ("models", "ChatHistory"),
        "ChatsFile": ("models", "ChatsFile"),
        "BaseChatRepository": ("repo", "BaseChatRepository"),
        "JsonChatRepository": ("repo", "JsonChatRepository"),
    }
    target = export_map.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = import_module(f".{module_name}", __name__)
    return getattr(module, attr_name)


def __dir__():
    """Expose lazily-loaded names to introspection tools."""
    return sorted(set(globals()) | set(__all__))


def __all__check():
    """No-op helper to keep static analyzers aligned with lazy exports."""
    return __all__


__all__check()
