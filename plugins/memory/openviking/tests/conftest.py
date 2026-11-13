# -*- coding: utf-8 -*-
"""Plugin test fixtures, including its runtime governance declaration."""

import logging

import pytest


@pytest.fixture(autouse=True)
def capture_qwenpaw_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let caplog observe records emitted through the app logger tree."""
    monkeypatch.setattr(logging.getLogger("qwenpaw"), "propagate", True)


@pytest.fixture(scope="session", autouse=True)
def register_plugin_contract():
    """Install the metadata normally registered when this plugin starts."""
    from qwenpaw.governance.tool_registry import (
        DEFAULT_REGISTRY,
        register_tool_governance,
    )
    from qwenpaw.plugins.api import release_tool_ownership_for_plugin

    plugin_id = "memory-openviking"
    register_tool_governance(
        DEFAULT_REGISTRY,
        python_name="openviking_memory_search",
        policy_name="OpenVikingMemorySearch",
        tool_type="network",
        target_param="query",
        owner=plugin_id,
    )
    try:
        yield
    finally:
        release_tool_ownership_for_plugin(plugin_id)
