# -*- coding: utf-8 -*-
"""Workspace module for agent lifecycle management.

This module provides unified workspace management including:
- Workspace: Single agent instance manager
- ServiceManager: Component lifecycle orchestration
- ServiceDescriptor: Declarative service configuration
"""

from .workspace import Workspace
from .service_manager import ServiceManager, ServiceDescriptor

__all__ = ["Workspace", "ServiceManager", "ServiceDescriptor"]
