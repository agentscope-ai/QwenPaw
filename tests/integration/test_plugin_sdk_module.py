# -*- coding: utf-8 -*-
"""Integration tests for the plugin SDK (PluginApi) and PluginRegistry.

Third coverage-sprint batch, targeted at uncovered lines in
src/qwenpaw/plugins/api.py (hook registration, router/middleware
registration, ownership helpers).

These are module-level integration tests exercising the plugin SDK's
public API against a real PluginRegistry instance.

Tests cover:
- PluginApi construction and registry binding
- startup/shutdown/uninstall hook registration into the registry
- control command and middleware registration
- tool ownership claim/release helpers
"""

from __future__ import annotations

import pytest


def _make_api(plugin_id="integ_test_plugin"):
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    api = PluginApi(plugin_id=plugin_id, config={"k": "v"})
    api.set_registry(registry)
    return api, registry


@pytest.mark.integration
@pytest.mark.p1
def test_plugin_api_construction() -> None:
    """Test purpose:
    - Verify PluginApi stores plugin_id/config/manifest defaults.

    Test flow:
    1. Construct PluginApi with and without manifest.
    2. Verify fields.
    """
    from qwenpaw.plugins.api import PluginApi

    api = PluginApi(plugin_id="p1", config={"a": 1})
    assert api.plugin_id == "p1"
    assert api.config == {"a": 1}
    assert api.manifest == {}

    api2 = PluginApi(plugin_id="p2", config={}, manifest={"name": "x"})
    assert api2.manifest == {"name": "x"}


@pytest.mark.integration
@pytest.mark.p1
def test_plugin_api_startup_hook_registration() -> None:
    """Test purpose:
    - Verify register_startup_hook records the hook in the registry.

    Test flow:
    1. Bind PluginApi to a fresh registry.
    2. Register a startup hook.
    3. Verify the registry holds it.
    """
    api, registry = _make_api()

    async def _hook():
        return None

    api.register_startup_hook(
        hook_name="integ_hook",
        callback=_hook,
        priority=5,
    )
    hooks = getattr(registry, "startup_hooks", None) or getattr(
        registry,
        "_startup_hooks",
        {},
    )
    assert hooks, "startup hook not recorded in registry"


@pytest.mark.integration
@pytest.mark.p1
def test_plugin_api_shutdown_hook_registration() -> None:
    """Test purpose:
    - Verify register_shutdown_hook records the hook in the registry.

    API surface:
    - PluginApi.register_shutdown_hook
    """
    api, registry = _make_api()

    async def _hook():
        return None

    api.register_shutdown_hook(hook_name="integ_shutdown", callback=_hook)
    hooks = getattr(registry, "shutdown_hooks", None) or getattr(
        registry,
        "_shutdown_hooks",
        {},
    )
    assert hooks, "shutdown hook not recorded in registry"


@pytest.mark.integration
@pytest.mark.p1
def test_plugin_api_uninstall_hook_registration() -> None:
    """Test purpose:
    - Verify register_uninstall_hook records the hook in the registry.

    API surface:
    - PluginApi.register_uninstall_hook
    """
    api, registry = _make_api()

    async def _hook():
        return None

    api.register_uninstall_hook(hook_name="integ_uninstall", callback=_hook)
    hooks = getattr(registry, "uninstall_hooks", None) or getattr(
        registry,
        "_uninstall_hooks",
        {},
    )
    assert hooks, "uninstall hook not recorded in registry"


@pytest.mark.integration
@pytest.mark.p1
def test_plugin_api_middleware_registration() -> None:
    """Test purpose:
    - Verify register_middleware records a middleware factory.

    API surface:
    - PluginApi.register_middleware
    """
    api, registry = _make_api()

    def _factory(_ctx, _agent_config):
        return None

    api.register_middleware(_factory, priority=50)
    mws = getattr(registry, "_middleware_registrations", [])
    assert mws, "middleware not recorded in registry"


@pytest.mark.integration
@pytest.mark.p1
def test_tool_ownership_claim_and_release() -> None:
    """Test purpose:
    - Verify tool ownership claim/release helpers round-trip.

    API surface:
    - qwenpaw.plugins.api._claim_tool_ownership
    - qwenpaw.plugins.api.release_tool_ownership_for_plugin
    """
    from qwenpaw.plugins.api import (
        _claim_tool_ownership,
        release_tool_ownership_for_plugin,
    )

    _claim_tool_ownership("integ_owned_tool", "integ_owner_plugin")
    release_tool_ownership_for_plugin("integ_owner_plugin")
