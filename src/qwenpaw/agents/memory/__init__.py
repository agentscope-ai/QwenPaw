# -*- coding: utf-8 -*-
"""Memory management module for QwenPaw agents."""

from .agent_md_manager import AgentMdManager
from .base_memory_manager import BaseMemoryManager
from .reme_light_memory_manager import ReMeLightMemoryManager

__all__ = [
    "AgentMdManager",
    "BaseMemoryManager",
    "ReMeLightMemoryManager",
]

_PROACTIVE_EXPORTS = {
    "ProactiveConfig",
    "ProactiveTask",
    "ProactiveQueryResult",
    "enable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "generate_proactive_response",
    "extract_content",
}


def __getattr__(name: str):
    if name in _PROACTIVE_EXPORTS:
        from . import proactive as _proactive  # noqa: PLC0415

        return getattr(_proactive, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
