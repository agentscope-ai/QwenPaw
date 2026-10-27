# -*- coding: utf-8 -*-
"""Install governance declarations normally owned by plugin startup."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def register_plugin_contract():
    """Exercise tests with the ADBPG governance metadata installed."""
    from qwenpaw.governance.tool_registry import (
        DEFAULT_REGISTRY,
        register_tool_governance,
    )
    from qwenpaw.plugins.api import release_tool_ownership_for_plugin

    plugin_id = "memory-adbpg"
    register_tool_governance(
        DEFAULT_REGISTRY,
        python_name="adbpg_memory_search",
        policy_name="ADBPGMemorySearch",
        tool_type="network",
        target_param="query",
        owner=plugin_id,
    )
    try:
        yield
    finally:
        release_tool_ownership_for_plugin(plugin_id)
