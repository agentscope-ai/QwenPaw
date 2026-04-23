# -*- coding: utf-8 -*-
"""Memory management module for QwenPaw agents."""

from typing import TYPE_CHECKING

from .agent_md_manager import AgentMdManager
from .base_memory_manager import BaseMemoryManager
from .reme_light_memory_manager import ReMeLightMemoryManager

# Proactive symbols are lazily re-exported via __getattr__ at runtime to
# avoid circular imports (proactive -> react_agent -> agents.memory loop).
# The TYPE_CHECKING block below satisfies static analysis tools (pylint, mypy).
if TYPE_CHECKING:  # pragma: no cover
    from .proactive import (
        ProactiveConfig,
        ProactiveQueryResult,
        ProactiveTask,
        enable_proactive_for_session,
        extract_content,
        generate_proactive_response,
        proactive_configs,
        proactive_tasks,
        proactive_trigger_loop,
    )

# pylint: disable=undefined-all-variable
__all__ = [
    "AgentMdManager",
    "BaseMemoryManager",
    "ReMeLightMemoryManager",
    # proactive symbols resolved lazily at runtime via __getattr__
    "ProactiveConfig",
    "ProactiveTask",
    "ProactiveQueryResult",
    "enable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "generate_proactive_response",
    "extract_content",
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
