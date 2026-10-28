# -*- coding: utf-8 -*-
"""Independent public SDK and transport tests for the MCP backend."""

from pathlib import Path
import sys
from types import ModuleType

# Import source helpers without executing plugin registration.
# Public integration tests load the real manifest through PluginTestHost.
_package = ModuleType("mcp_plugin_under_test")
_package.__path__ = [
    str(Path(__file__).resolve().parents[4] / "plugins/protocol/mcp"),
]
sys.modules["mcp_plugin_under_test"] = _package
