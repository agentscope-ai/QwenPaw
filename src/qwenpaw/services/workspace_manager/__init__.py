# -*- coding: utf-8 -*-
"""WorkspaceManager + Sandbox — per-workspace resource boundary management.

Concrete implementations are provided by a separate workstream.
This package defines the interface contracts only.
"""

from .sandbox import Sandbox, SandboxViolationError
from .workspace_manager import WorkspaceManager

__all__ = ["Sandbox", "SandboxViolationError", "WorkspaceManager"]
