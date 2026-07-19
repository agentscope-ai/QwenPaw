# -*- coding: utf-8 -*-
"""Background subagent lifecycle management."""

from .context import SubagentSpawnContext, get_subagent_spawn_context
from .manager import (
    SubagentLifecycleEvent,
    SubagentStatus,
    SubagentTaskManager,
    SubagentTaskRecord,
)

__all__ = [
    "SubagentLifecycleEvent",
    "SubagentSpawnContext",
    "SubagentStatus",
    "SubagentTaskManager",
    "SubagentTaskRecord",
    "get_subagent_spawn_context",
]
