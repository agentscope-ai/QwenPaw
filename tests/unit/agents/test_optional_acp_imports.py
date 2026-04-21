# -*- coding: utf-8 -*-
"""Regression tests for optional ACP imports."""

from __future__ import annotations

import importlib
import sys


def _reload_module(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_tools_package_imports_without_acp_server_dependency():
    sys.modules.pop("qwenpaw.agents.acp.tool_adapter", None)
    sys.modules.pop("qwenpaw.agents.tools.delegate_external_agent", None)

    tools_module = _reload_module("qwenpaw.agents.tools")

    assert hasattr(tools_module, "delegate_external_agent")


def test_acp_package_exposes_service_symbols_without_loading_server():
    acp_module = _reload_module("qwenpaw.agents.acp")

    assert hasattr(acp_module, "get_acp_service")
    assert "qwenpaw.agents.acp.server" not in sys.modules
