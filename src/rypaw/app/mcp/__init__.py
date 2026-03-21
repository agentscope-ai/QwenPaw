# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) client management module.

This module provides hot-reloadable MCP client management,
completely independent from other app components.
"""

from .manager import MCPClientManager
from .watcher import MCPConfigWatcher

__all__ = [
    "MCPClientManager",
    "MCPConfigWatcher",
]
