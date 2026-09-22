# -*- coding: utf-8 -*-
"""Install the governance declarations normally owned by plugin startup."""

import logging

import pytest


@pytest.fixture(autouse=True)
def capture_qwenpaw_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let caplog observe records emitted through the app logger tree."""
    monkeypatch.setattr(logging.getLogger("qwenpaw"), "propagate", True)


@pytest.fixture(scope="session", autouse=True)
def register_plugin_contract():
    """Exercise tests with the governance metadata installed by the plugin."""
    from qwenpaw.governance.tool_registry import (
        DEFAULT_REGISTRY,
        register_tool_governance,
    )
    from qwenpaw.plugins.api import release_tool_ownership_for_plugin

    plugin_id = "memory-powercontext"
    register_tool_governance(
        DEFAULT_REGISTRY,
        python_name="powercontext_memory_search",
        policy_name="PowerContextMemorySearch",
        tool_type="network",
        target_param="query",
        owner=plugin_id,
    )
    register_tool_governance(
        DEFAULT_REGISTRY,
        python_name="powercontext_memory_remember",
        policy_name="PowerContextMemoryRemember",
        tool_type="network",
        owner=plugin_id,
    )
    try:
        yield
    finally:
        release_tool_ownership_for_plugin(plugin_id)
