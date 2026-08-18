# -*- coding: utf-8 -*-
"""Regression tests for zero-downtime reloads racing config writes.

A reload that began before the latest ``save_agent_config`` builds its
replacement workspace from the pre-write snapshot; installing it after
the write would make a fresh PUT invisible until yet another rebuild
landed.  ``note_agent_config_changed`` bumps a per-agent generation so
such stale swaps abort and the writer's own scheduled reload delivers
the fresh state.
"""

# Pytest fixtures intentionally provide setup-only arguments to tests.
# pylint: disable=protected-access,redefined-outer-name,unused-argument

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.multi_agent_manager import MultiAgentManager


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
def manager(monkeypatch):
    mgr = MultiAgentManager()
    old_instance = _fake_workspace()
    mgr.agents["agent"] = old_instance

    profile = SimpleNamespace(workspace_dir="/tmp/ws/agent")
    fake_config = SimpleNamespace(
        agents=SimpleNamespace(profiles={"agent": profile}),
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
    return mgr, old_instance


async def test_stale_reload_aborts_when_config_changes_mid_build(manager):
    """A write during the rebuild must discard the pre-write snapshot."""
    mgr, old_instance = manager
    new_instance = _fake_workspace()
    build_gate = asyncio.Event()

    def create_workspace(agent_id: str, workspace_dir: str):
        return new_instance

    mgr._create_workspace = create_workspace

    async def gated_start() -> None:
        await build_gate.wait()

    new_instance.start = gated_start

    reload_task = asyncio.create_task(mgr.reload_agent("agent"))
    await asyncio.sleep(0)  # let the reload capture its generation

    # A config write lands while the replacement is still building.
    mgr.note_agent_config_changed("agent")
    build_gate.set()

    assert await reload_task is False
    assert mgr.agents["agent"] is old_instance
    new_instance.stop.assert_awaited()


async def test_reload_swaps_when_no_write_intervenes(manager):
    mgr, old_instance = manager
    new_instance = _fake_workspace()
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    assert await mgr.reload_agent("agent") is True
    assert mgr.agents["agent"] is new_instance
    assert mgr.agents["agent"] is not old_instance


async def test_writers_reload_lands_after_stale_abort(manager):
    """The bumping writer's own reload installs the fresh workspace."""
    mgr, _old_instance = manager
    stale_instance = _fake_workspace()
    fresh_instance = _fake_workspace()
    instances = [stale_instance, fresh_instance]
    build_gate = asyncio.Event()

    def create_workspace(agent_id: str, workspace_dir: str):
        return instances.pop(0)

    mgr._create_workspace = create_workspace

    async def gated_start() -> None:
        await build_gate.wait()

    stale_instance.start = gated_start

    stale_task = asyncio.create_task(mgr.reload_agent("agent"))
    await asyncio.sleep(0)

    # Writer: bump then reload (the schedule_agent_reload contract).
    mgr.note_agent_config_changed("agent")
    build_gate.set()
    assert await stale_task is False

    assert await mgr.reload_agent("agent") is True
    assert mgr.agents["agent"] is fresh_instance
