# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) client management module.

This module provides hot-reloadable MCP client management,
completely independent from other app components.

It also provides drop-in replacements for AgentScope's MCP clients
that solve the CPU leak issue caused by cross-task context manager exits.
"""

from .manager import MCPClientManager
from .stateful_client import HttpStatefulClient, StdIOStatefulClient
from .watcher import MCPConfigWatcher

__all__ = [
    "HttpStatefulClient",
    "MCPClientManager",
    "MCPConfigWatcher",
    "StdIOStatefulClient",
]
