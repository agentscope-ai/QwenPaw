# -*- coding: utf-8 -*-
"""Memory management module for QwenPaw agents."""

from typing import TYPE_CHECKING

from .agent_md_manager import AgentMdManager
from .action_provider import (
    MemoryActionProvider,
    MemoryActionResponse,
    MemoryActionResult,
    MemoryActionSpec,
)
from .base_memory_manager import BaseMemoryManager
from .reme_light_memory_manager import ReMeLightMemoryManager
from .dummy import (
    NoopMemoryManager,
)  # registers "none" backend

# Proactive symbols are lazily re-exported via __getattr__ at runtime to
# avoid circular imports (proactive -> react_agent -> agents.memory loop).
# The TYPE_CHECKING block below satisfies static analysis tools (pylint, mypy).
if TYPE_CHECKING:  # pragma: no cover
    from .proactive import (
        AgendaItem,
        AgendaRound,
        ProactiveConfig,
        ProactiveSettings,
        build_agenda_receipt,
        deliver_proactive_round,
        disable_proactive_for_session,
        enable_proactive_for_session,
        load_proactive_settings,
        proactive_configs,
        proactive_tasks,
        proactive_trigger_loop,
    )

# pylint: disable=undefined-all-variable
__all__ = [
    "AgentMdManager",
    "MemoryActionProvider",
    "MemoryActionResponse",
    "MemoryActionResult",
    "MemoryActionSpec",
    "BaseMemoryManager",
    "ReMeLightMemoryManager",
    "NoopMemoryManager",
    # proactive symbols resolved lazily at runtime via __getattr__
    "AgendaItem",
    "AgendaRound",
    "ProactiveConfig",
    "ProactiveSettings",
    "build_agenda_receipt",
    "deliver_proactive_round",
    "enable_proactive_for_session",
    "disable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "load_proactive_settings",
]

_PROACTIVE_EXPORTS = {
    "AgendaItem",
    "AgendaRound",
    "ProactiveConfig",
    "ProactiveSettings",
    "build_agenda_receipt",
    "deliver_proactive_round",
    "enable_proactive_for_session",
    "disable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "load_proactive_settings",
}


def __getattr__(name: str):
    if name in _PROACTIVE_EXPORTS:
        from . import proactive as _proactive  # noqa: PLC0415

        return getattr(_proactive, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
