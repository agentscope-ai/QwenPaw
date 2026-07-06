# -*- coding: utf-8 -*-
"""Cross-workspace coordination services held by FastAPI lifespan.

The AppServiceManager is the ONLY cross-workspace container, and it is
*strictly* limited to three coordinators:

* ``task_tracker``         — observability for streaming runs
* ``tool_coordinator``     — HITL tool-call coordination
* ``approval_coordinator`` — HITL approval coordination

Any state that should be per-workspace (ToolRegistry, PromptManager,
SlashCommandRegistry, HookRegistry, modes, ...) belongs on
``Workspace.service_manager`` / ``Workspace.plugins`` instead — never here.
"""

from __future__ import annotations

from .app_service_manager import AppServiceManager
from .approval_coordinator import ApprovalCoordinator
from ...tool_calls import ToolCallEntry, ToolCoordinator

__all__ = [
    "AppServiceManager",
    "ApprovalCoordinator",
    "ToolCallEntry",
    "ToolCoordinator",
]
