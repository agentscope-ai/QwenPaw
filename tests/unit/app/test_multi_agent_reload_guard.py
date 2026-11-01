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
    ws.cancel_active_requests = AsyncMock()
    ws.set_manager = MagicMock()
    ws.set_task_tracker = MagicMock()
    ws.set_reusable_components = AsyncMock()
    ws.channel_manager = None
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
    new_instance.stop.assert_awaited_once_with(
        final=True,
        preserve_reused=True,
    )


async def test_reload_swaps_when_no_write_intervenes(manager):
    mgr, old_instance = manager
    new_instance = _fake_workspace()
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    assert await mgr.reload_agent("agent") is True
    assert mgr.agents["agent"] is new_instance
    assert mgr.agents["agent"] is not old_instance
    new_instance.start.assert_awaited_once_with()
    new_instance.set_manager.assert_called_once_with(mgr)


async def test_reload_candidate_starts_once_with_crons_and_channels_deferred(
    manager,
):
    mgr, old_instance = manager
    candidate = _fake_workspace()
    states = []

    async def observe_start():
        states.append(
            (candidate.cron_start_paused, candidate._defer_channel_start),
        )
        candidate.set_manager.assert_called_once_with(mgr)
        assert mgr.agents["agent"] is old_instance

    candidate.start.side_effect = observe_start
    mgr._create_workspace = lambda agent_id, workspace_dir: candidate
    assert await mgr.reload_agent("agent")
    assert states == [(True, True)]
    candidate.start.assert_awaited_once_with()
    assert mgr.agents["agent"] is candidate
    candidate.cron_manager.handoff_from.assert_called_once_with(
        old_instance.cron_manager,
    )


async def test_cancelled_plugin_setup_cleans_uncommitted_candidate(manager):
    mgr, old_instance = manager
    new_instance = _fake_workspace()
    plugin_setup_entered = asyncio.Event()
    mgr._create_workspace = lambda agent_id, workspace_dir: new_instance

    async def blocking_plugin_setup(*_args) -> None:
        plugin_setup_entered.set()
        await asyncio.Event().wait()

    mgr._setup_workspace_plugins = blocking_plugin_setup

    reload_task = asyncio.create_task(mgr.reload_agent("agent"))
    await plugin_setup_entered.wait()
    reload_task.cancel("reload cancelled")

    with pytest.raises(asyncio.CancelledError, match="reload cancelled"):
        await reload_task

    new_instance.stop.assert_awaited_once_with(
        final=True,
        preserve_reused=True,
    )
    assert mgr.agents["agent"] is old_instance


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


@pytest.mark.parametrize("delayed", [False, True])
async def test_retired_workspace_stop_failure_retries(monkeypatch, delayed):
    mgr = MultiAgentManager()
    old, new = _fake_workspace(), _fake_workspace()
    mgr.agents["agent"] = new
    retry_started, release_retry = asyncio.Event(), asyncio.Event()

    async def stop(**_kwargs):
        if old.stop.await_count == 1:
            raise RuntimeError("plugin still alive")
        retry_started.set()
        await release_retry.wait()

    old.stop.side_effect = stop
    old.task_tracker.wait_tasks_done = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager._OLD_WORKSPACE_CLEANUP_RETRY_SECONDS",
        0,
    )
    active = {"request": asyncio.get_running_loop().create_future()}
    try:
        await mgr._graceful_stop_old_instance(
            old,
            "agent",
            active_tasks=active if delayed else {},
        )
        await asyncio.wait_for(retry_started.wait(), timeout=1)
        assert mgr._retired_instances[id(old)] is old
        assert mgr.agents["agent"] is new
        new.stop.assert_not_awaited()
        release_retry.set()
        await asyncio.gather(*mgr._cleanup_tasks)
        assert id(old) not in mgr._retired_instances
        assert old.stop.await_count == 2
        assert all(
            call.kwargs == {"final": False}
            for call in old.stop.await_args_list
        )
    finally:
        release_retry.set()
        await mgr.cancel_all_cleanup_tasks()


async def test_shutdown_retries_retired_workspace_preserving_reused_services(
    monkeypatch,
):
    mgr = MultiAgentManager()
    old, new = _fake_workspace(), _fake_workspace()
    mgr.agents["agent"] = new
    old.stop.side_effect = [RuntimeError("plugin still alive"), None]
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager._OLD_WORKSPACE_CLEANUP_RETRY_SECONDS",
        60,
    )
    await mgr._graceful_stop_old_instance(old, "agent", active_tasks={})
    assert mgr._retired_instances[id(old)] is old
    await mgr.stop_all()
    assert not mgr._cleanup_tasks
    assert not mgr._retired_instances
    assert old.stop.await_count == 2
    assert all(
        call.kwargs == {"final": False} for call in old.stop.await_args_list
    )
    new.stop.assert_awaited_once_with()
    old.cancel_active_requests.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("replace_instance", [False, True])
async def test_stop_reuses_instance_task_without_removing_replacement(
    replace_instance,
):
    """Concurrent stops share work and preserve a replacement agent."""
    mgr = MultiAgentManager()
    started, release = asyncio.Event(), asyncio.Event()

    async def stop():
        started.set()
        await release.wait()

    old = SimpleNamespace(stop=AsyncMock(side_effect=stop))
    new = SimpleNamespace(stop=AsyncMock())
    mgr.agents["agent"] = old
    first = asyncio.create_task(mgr.stop_agent("agent"))
    await asyncio.wait_for(started.wait(), 1)
    second = asyncio.create_task(mgr.stop_agent("agent"))
    await asyncio.sleep(0)
    if replace_instance:
        mgr.agents["agent"] = new
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    old.stop.assert_awaited_once()
    new.stop.assert_not_awaited()
    if replace_instance:
        assert mgr.agents["agent"] is new
    else:
        assert "agent" not in mgr.agents


class _ControlledStopWorkspace:
    """Workspace lifecycle boundary with observable completion and failure."""

    def __init__(self, agent_id, *, blocked=False, fail=False):
        self.agent_id = agent_id
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stopped = asyncio.Event()
        self.fail = fail
        self.cancel_active_requests = AsyncMock()
        self.final_modes = []
        if not blocked:
            self.release.set()

    async def stop(self, *, final=True):
        self.final_modes.append(final)
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError(f"{self.agent_id} runtime still alive")
        self.stopped.set()


@pytest.mark.parametrize(
    "unavailable",
    ["stopping", "uninstalling", "closing"],
)
async def test_cached_agent_lookup_refuses_unavailable_instance(unavailable):
    mgr = MultiAgentManager()
    workspace = _ControlledStopWorkspace("agent", blocked=True)
    mgr.agents["agent"] = workspace
    stopping = None
    if unavailable == "stopping":
        stopping = asyncio.create_task(mgr.stop_agent("agent"))
        await asyncio.wait_for(workspace.started.wait(), 1)
    elif unavailable == "uninstalling":
        mgr.reserve_agent_uninstall(["agent"])
    else:
        mgr._closing = True
    try:
        with pytest.raises(RuntimeError, match="stopping|uninstalled"):
            await mgr.get_agent("agent")
        assert mgr.agents["agent"] is workspace
        assert not workspace.stopped.is_set()
    finally:
        workspace.release.set()
        if stopping is not None:
            await stopping


async def test_parallel_shutdown_retains_failed_current_and_retired():
    from qwenpaw.plugins.lifecycle import QuiescenceError

    mgr = MultiAgentManager()
    healthy = _ControlledStopWorkspace("healthy")
    current = _ControlledStopWorkspace("current", blocked=True, fail=True)
    retired = _ControlledStopWorkspace("retired", blocked=True, fail=True)
    mgr.agents.update(healthy=healthy, current=current)
    mgr._retired_instances[id(retired)] = retired
    shutdown = asyncio.create_task(mgr.stop_all())
    try:
        await asyncio.wait_for(
            asyncio.gather(
                healthy.stopped.wait(),
                current.started.wait(),
                retired.started.wait(),
            ),
            1,
        )
        assert not shutdown.done()
        with pytest.raises(RuntimeError, match="stopping"):
            await mgr.get_agent("current")
        current.release.set()
        retired.release.set()
        with pytest.raises(QuiescenceError, match="cleanup failed"):
            await shutdown
        assert mgr.agents == {"current": current}
        assert mgr._retired_instances == {id(retired): retired}
        assert retired.final_modes == [False]

        current.fail = retired.fail = False
        await mgr.stop_all()
        assert current.stopped.is_set() and retired.stopped.is_set()
        assert not mgr.agents and not mgr._retired_instances
        assert not mgr._agent_stop_tasks
        assert retired.final_modes == [False, False]
    finally:
        current.release.set()
        retired.release.set()
        if not shutdown.done():
            shutdown.cancel()
        await asyncio.gather(shutdown, return_exceptions=True)


async def test_stop_agent_retries_failed_retired_cleanup(monkeypatch):
    """A failed old workspace remains owned without stopping another agent."""
    mgr = MultiAgentManager()
    old = _fake_workspace()
    old.agent_id = "agent"
    current, other = _fake_workspace(), _fake_workspace()
    mgr.agents.update(agent=current, other=other)
    old.stop.side_effect = [RuntimeError("busy"), RuntimeError("busy"), None]
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager._OLD_WORKSPACE_CLEANUP_RETRY_SECONDS",
        60,
    )
    await mgr._graceful_stop_old_instance(old, "agent", active_tasks={})
    try:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(mgr.stop_agent("agent"), 1)
        assert mgr._retired_instances[id(old)] is old
        assert mgr.agents["agent"] is current
        current.stop.assert_not_awaited()
        other.stop.assert_not_awaited()

        assert await asyncio.wait_for(mgr.stop_agent("agent"), 1)
        assert id(old) not in mgr._retired_instances
        assert mgr.agents == {"other": other}
        current.stop.assert_awaited_once_with()
        other.stop.assert_not_awaited()
        assert old.stop.await_count == 3
    finally:
        await mgr.cancel_all_cleanup_tasks()


async def test_cancelled_stop_caller_keeps_retired_cleanup_owned(monkeypatch):
    """Cancelled callers leave cleanup owned and the manager lock available."""
    mgr = MultiAgentManager()
    old = _fake_workspace()
    old.agent_id = "agent"
    current = _fake_workspace()
    mgr.agents["agent"] = current
    entered, release = asyncio.Event(), asyncio.Event()

    async def stop(**_kwargs):
        if old.stop.await_count == 1:
            raise RuntimeError("busy")
        async with mgr._lock:
            entered.set()
            await release.wait()

    old.stop.side_effect = stop
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager._OLD_WORKSPACE_CLEANUP_RETRY_SECONDS",
        60,
    )
    await mgr._graceful_stop_old_instance(old, "agent", active_tasks={})
    caller = asyncio.create_task(mgr.stop_agent("agent"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert mgr._retired_instances[id(old)] is old
        assert mgr.agents["agent"] is current
        current.stop.assert_not_awaited()
        release.set()
        assert await asyncio.wait_for(mgr.stop_agent("agent"), 1)
        assert not mgr._retired_instances
        assert not mgr._agent_stop_tasks
        assert not mgr.agents
        assert old.stop.await_count == 2
        current.stop.assert_awaited_once_with()
    finally:
        release.set()
        await mgr.cancel_all_cleanup_tasks()
