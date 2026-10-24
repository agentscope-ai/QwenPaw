# -*- coding: utf-8 -*-
"""Install the governance declarations normally owned by plugin startup."""

import logging
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def capture_qwenpaw_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let caplog observe records emitted through the app logger tree."""
    monkeypatch.setattr(logging.getLogger("qwenpaw"), "propagate", True)


@pytest.fixture(scope="session", autouse=True)
def register_plugin_contract():
    """Exercise tests with the governance metadata installed by the plugin."""
    from plugins.memory.powercontext import backend
    from qwenpaw.memory import memory_registry
    from qwenpaw.plugins.api import (
        PluginApi,
        release_tool_ownership_for_plugin,
    )

    plugin_id = "memory-powercontext"
    plugin_path = Path(__file__).parents[1] / "plugin.py"
    with patch.dict(sys.modules, {"backend": backend}):
        plugin = runpy.run_path(str(plugin_path))["plugin"]
    plugin.register(PluginApi(plugin_id, config={}))
    try:
        yield
    finally:
        memory_registry.unregister_owner(plugin_id)
        release_tool_ownership_for_plugin(plugin_id)
