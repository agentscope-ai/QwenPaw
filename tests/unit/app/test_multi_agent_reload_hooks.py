# -*- coding: utf-8 -*-
"""Regression tests for workspace_created hooks fired by reload_agent.

``/daemon restart`` rebuilds a workspace in-process via
``MultiAgentManager.reload_agent``.  Plugin-contributed slash commands,
modes and tools only enter a freshly built workspace through its
``workspace_created`` hooks: the startup hook runs once per process, so
a reload that skipped the hooks left the replacement instance without
any plugin registrations until the whole app restarted.

The fix fires the hooks right after the atomic swap, under the same
contract as the lazy-load path in ``get_agent``:

- the hooks run only after ``self.agents`` already maps the agent to
  the replacement instance (plugins resolve the workspace through the
  registry's workspace manager at hook run time);
- the ``workspace_info`` payload matches the lazy-load payload;
- a failing hook must not roll back or crash the committed reload;
- a candidate that fails to start is never announced to plugins.
"""

# Pytest fixtures intentionally provide setup-only arguments to tests.
# pylint: disable=protected-access,redefined-outer-name,unused-argument

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.plugins.registry import PluginRegistry

AGENT_ID = "agent"
WORKSPACE_DIR = "/tmp/ws/agent"
HOOK_PAYLOAD = {"agent_id": AGENT_ID, "workspace_dir": WORKSPACE_DIR}


def _fake_workspace() -> MagicMock:
    ws = MagicMock()
    ws.start = AsyncMock()
    ws.stop = AsyncMock()
    ws.set_manager = MagicMock()
    ws.set_task_tracker = MagicMock()
    ws.set_reusable_components = AsyncMock()
    ws._service_manager.services.get.return_value = None
    ws._service_manager.get_reusable_services.return_value = {}
    ws.task_tracker.snapshot_active_tasks = AsyncMock(return_value=[])
    return ws


@pytest.fixture
def fresh_plugin_registry():
    """Isolate the PluginRegistry singleton for the current test."""
    old_singleton = PluginRegistry._instance
    PluginRegistry._instance = None
    yield PluginRegistry()
    PluginRegistry._instance = old_singleton


@pytest.fixture
def manager(monkeypatch):
    mgr = MultiAgentManager()
    old_instance = _fake_workspace()
    mgr.agents[AGENT_ID] = old_instance

    profile = SimpleNamespace(workspace_dir=WORKSPACE_DIR)
    fake_config = SimpleNamespace(
        agents=SimpleNamespace(profiles={AGENT_ID: profile}),
    )
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr(
        mgr,
        "_graceful_stop_old_instance",
        AsyncMock(),
    )
    monkeypatch.setattr(
        mgr,
        "_mark_rejected_reusable_services_for_cleanup",
        MagicMock(),
    )
    monkeypatch.setattr(
        mgr,
        "_setup_workspace_plugins",
        AsyncMock(),
    )
    return mgr, old_instance


@pytest.fixture
def hook_spy(monkeypatch):
    """AsyncMock standing in for the classmethod hook dispatch."""
    spy = AsyncMock()
    monkeypatch.setattr(
        MultiAgentManager,
        "_fire_workspace_created_hooks",
        spy,
    )
    return spy


async def test_reload_fires_hooks_with_lazy_load_payload(
    manager,
    hook_spy,
):
    """A committed reload fires the hooks once with the expected payload."""
    mgr, _old_instance = manager
    new_instance = _fake_workspace()
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    assert await mgr.reload_agent(AGENT_ID) is True

    hook_spy.assert_awaited_once_with(HOOK_PAYLOAD)


async def test_hooks_run_after_swap_and_target_new_instance(
    manager,
    fresh_plugin_registry,
):
    """Hooks resolve the replacement workspace, never the old one.

    Mirrors the real plugin path (``_get_workspace_from_info``): a hook
    that receives no explicit ``workspace`` key looks the instance up
    through the registry's workspace manager, so it only lands on the
    new instance when the fire happens *after* the atomic swap.
    """
    mgr, old_instance = manager
    fresh_plugin_registry.set_workspace_manager(mgr)
    new_instance = _fake_workspace()
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    invocations = []

    def plugin_hook(workspace_info: dict) -> None:
        ws = workspace_info.get("workspace")
        if ws is None:
            ws = (
                PluginRegistry()
                .get_workspace_manager()
                .agents.get(
                    workspace_info["agent_id"],
                )
            )
        invocations.append((workspace_info, ws))
        ws.plugins.slash_command_registry.register("plugin-cmd")

    # Not reload-safe: only the post-swap fire may run this hook —
    # exactly the path the daemon-restart bug used to skip.
    fresh_plugin_registry.register_workspace_created_hook(
        plugin_id="test-plugin",
        hook_name="re_register_plugin_cmd",
        callback=plugin_hook,
    )

    assert await mgr.reload_agent(AGENT_ID) is True

    fired = [info for info, _ws in invocations if "workspace" not in info]
    assert fired == [HOOK_PAYLOAD]
    for _info, ws in invocations:
        assert ws is new_instance
    new_registry = new_instance.plugins.slash_command_registry
    new_registry.register.assert_called_once_with("plugin-cmd")
    old_registry = old_instance.plugins.slash_command_registry
    old_registry.register.assert_not_called()


async def test_failing_hook_does_not_break_committed_reload(
    manager,
    fresh_plugin_registry,
):
    """A crashing hook is isolated; the reload still finishes."""
    mgr, _old_instance = manager
    fresh_plugin_registry.set_workspace_manager(mgr)
    new_instance = _fake_workspace()
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    def broken_hook(workspace_info: dict) -> None:
        raise RuntimeError("plugin hook crashed")

    healthy_calls = []

    def healthy_hook(workspace_info: dict) -> None:
        healthy_calls.append(workspace_info)

    fresh_plugin_registry.register_workspace_created_hook(
        plugin_id="test-plugin",
        hook_name="broken",
        callback=broken_hook,
        priority=10,
    )
    fresh_plugin_registry.register_workspace_created_hook(
        plugin_id="test-plugin",
        hook_name="healthy",
        callback=healthy_hook,
        priority=20,
    )

    assert await mgr.reload_agent(AGENT_ID) is True
    assert mgr.agents[AGENT_ID] is new_instance
    assert healthy_calls == [HOOK_PAYLOAD]


async def test_failed_candidate_start_skips_hooks(
    manager,
    hook_spy,
):
    """A candidate that fails to start is never announced to plugins."""
    mgr, old_instance = manager
    new_instance = _fake_workspace()
    new_instance.start = AsyncMock(side_effect=RuntimeError("boom"))
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    assert await mgr.reload_agent(AGENT_ID) is False
    assert mgr.agents[AGENT_ID] is old_instance
    hook_spy.assert_not_awaited()


async def test_lazy_load_and_reload_fire_identical_payload(
    monkeypatch,
    hook_spy,
):
    """reload_agent sends exactly the workspace_info get_agent sends."""
    mgr = MultiAgentManager()  # empty: force the lazy-load path first
    monkeypatch.setattr(
        mgr,
        "_setup_workspace_plugins",
        AsyncMock(),
    )
    profile = SimpleNamespace(workspace_dir=WORKSPACE_DIR)
    fake_config = SimpleNamespace(
        agents=SimpleNamespace(profiles={AGENT_ID: profile}),
    )
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: fake_config,
    )
    mgr._create_workspace = lambda agent_id, workspace_dir: _fake_workspace()

    await mgr.get_agent(AGENT_ID)
    assert await mgr.reload_agent(AGENT_ID) is True

    assert hook_spy.await_count == 2
    lazy_load_args = hook_spy.await_args_list[0].args
    reload_args = hook_spy.await_args_list[1].args
    assert reload_args == lazy_load_args == (HOOK_PAYLOAD,)
