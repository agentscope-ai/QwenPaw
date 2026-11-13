# -*- coding: utf-8 -*-
"""Workspace module for agent lifecycle management.

This module provides unified workspace management including:
- Workspace: Single agent instance manager (with per-workspace plugins)
- WorkspacePlugins: Per-workspace pluggable registries
- ServiceManager: Component lifecycle orchestration
- ServiceDescriptor: Declarative service configuration
"""

from .workspace import Workspace
from .workspace_plugins import WorkspacePlugins
from .service_manager import ServiceManager, ServiceDescriptor

__all__ = [
    "Workspace",
    "WorkspacePlugins",
    "ServiceManager",
    "ServiceDescriptor",
]
