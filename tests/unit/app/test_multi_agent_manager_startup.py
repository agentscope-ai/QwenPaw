# -*- coding: utf-8 -*-
"""Tests for bounded multi-agent startup scheduling."""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import qwenpaw.app.multi_agent_manager as multi_agent_manager_module
import qwenpaw.constant as constants
from qwenpaw.app.agent_startup import AgentStartupStatus
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.task_tracker import REPLAY_END_SSE, TaskTracker
from qwenpaw.app.workspace import Workspace
from qwenpaw.agents.memory.adbpg_memory_manager import ADBPGMemoryManager
from qwenpaw.agents.memory.dummy import NoopMemoryManager
from qwenpaw.agents.memory.powercontext_memory_manager import (
    PowerContextMemoryManager,
)
from qwenpaw.constant import BUILTIN_QA_AGENT_ID
from qwenpaw.config.config import PowerContextMemoryConfig


def _config(*agent_ids: str):
    profiles = {
        agent_id: SimpleNamespace(
            id=agent_id,
            workspace_dir=f"/tmp/{agent_id}",
            enabled=True,
        )
        for agent_id in agent_ids
    }
    return SimpleNamespace(
        agents=SimpleNamespace(profiles=profiles),
    )


class _ReloadServiceManager:
    def __init__(
        self,
        reusable: dict | None = None,
        accepted: set[str] | None = None,
    ) -> None:
        self.services = {}
        self._reusable = reusable or {}
        self.reused_services = accepted or set()
        self.descriptors = {
            name: SimpleNamespace(reusable=True) for name in self._reusable
        }

    def get_reusable_services(self) -> dict:
        return self._reusable


class _ReloadWorkspace:
    def __init__(
        self,
        agent_id: str,
        *,
        reusable: dict | None = None,
        accepted: set[str] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.task_tracker = TaskTracker()
        self._service_manager = _ReloadServiceManager(reusable, accepted)
        self.started = False
        self.stopped = False
        self.manager = None

    def set_task_tracker(self, task_tracker: TaskTracker) -> None:
        assert not self.started
        self.task_tracker = task_tracker

    async def set_reusable_components(self, _components: dict) -> None:
        return None

    async def start(self) -> None:
        self.started = True

    def set_manager(self, manager: MultiAgentManager) -> None:
        self.manager = manager

    async def stop(self, final: bool = True) -> None:
        del final
        self.stopped = True


def test_get_loaded_agent_never_starts_a_workspace() -> None:
    manager = MultiAgentManager()
    workspace = MagicMock()
    manager.agents["loaded"] = workspace

    assert manager.get_loaded_agent("loaded") is workspace
    assert manager.get_loaded_agent("not-loaded") is None


def test_workspace_reload_reuses_memory_manager(tmp_path) -> None:
    workspace = Workspace(
        agent_id="agent-1",
        workspace_dir=str(tmp_path),
    )

    descriptor = workspace._service_manager.descriptors["memory_manager"]
    assert descriptor.reusable is True


@pytest.mark.asyncio
async def test_workspace_replaces_reused_memory_manager_after_backend_switch(
    tmp_path,
) -> None:
    workspace = Workspace(
        agent_id="agent-1",
        workspace_dir=str(tmp_path),
    )
    workspace._config = SimpleNamespace(
        running=SimpleNamespace(memory_manager_backend="none"),
    )
    old_manager = ADBPGMemoryManager(str(tmp_path), "agent-1")

    await workspace.set_reusable_components(
        {"memory_manager": old_manager},
    )
    descriptor = workspace._service_manager.descriptors["memory_manager"]
    await workspace._service_manager._start_service(descriptor)

    assert isinstance(workspace.memory_manager, NoopMemoryManager)
    assert workspace.memory_manager is not old_manager
    assert "memory_manager" not in workspace._service_manager.reused_services


@pytest.mark.asyncio
async def test_workspace_keeps_reused_manager_when_backend_is_unchanged(
    tmp_path,
) -> None:
    workspace = Workspace(
        agent_id="agent-1",
        workspace_dir=str(tmp_path),
    )
    workspace._config = SimpleNamespace(
        running=SimpleNamespace(memory_manager_backend="none"),
    )
    old_manager = NoopMemoryManager(str(tmp_path), "agent-1")

    await workspace.set_reusable_components(
        {"memory_manager": old_manager},
    )
    descriptor = workspace._service_manager.descriptors["memory_manager"]
    await workspace._service_manager._start_service(descriptor)

    assert workspace.memory_manager is old_manager
    assert "memory_manager" in workspace._service_manager.reused_services


@pytest.mark.asyncio
async def test_workspace_recreates_powercontext_manager_when_config_changes(
    monkeypatch,
    tmp_path,
) -> None:
    """A reload must not keep a client with the old remote scope or URL."""
    old_config = PowerContextMemoryConfig(
        base_url="http://old.example",
        scope_id="agent:old",
    )
    new_config = PowerContextMemoryConfig(
        base_url="http://new.example",
        scope_id="agent:new",
    )
    workspace = Workspace(
        agent_id="agent-1",
        workspace_dir=str(tmp_path),
    )
    workspace._config = SimpleNamespace(
        running=SimpleNamespace(
            memory_manager_backend="powercontext",
            powercontext_memory_config=new_config,
        ),
    )
    old_manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    old_manager._config = old_config
    monkeypatch.setattr(
        "qwenpaw.agents.memory.powercontext_memory_manager.load_agent_config",
        lambda _agent_id: SimpleNamespace(
            running=SimpleNamespace(powercontext_memory_config=new_config),
        ),
    )

    await workspace.set_reusable_components(
        {"memory_manager": old_manager},
    )
    descriptor = workspace._service_manager.descriptors["memory_manager"]
    await workspace._service_manager._start_service(descriptor)

    manager = workspace.memory_manager
    assert manager is not old_manager
    assert isinstance(manager, PowerContextMemoryManager)
    assert manager._client is not None
    assert manager._client.config.base_url == "http://new.example"
    assert manager._client.config.scope_id == "agent:new"
    await manager.close()


@pytest.mark.asyncio
async def test_reload_marks_rejected_reusable_service_for_cleanup(
    monkeypatch,
) -> None:
    manager = MultiAgentManager()
    config = _config("agent-1")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    memory_manager = object()
    old_workspace = _ReloadWorkspace(
        "agent-1",
        reusable={"memory_manager": memory_manager},
        accepted={"memory_manager"},
    )
    new_workspace = _ReloadWorkspace("agent-1", accepted=set())
    manager.agents["agent-1"] = old_workspace
    manager._create_workspace = MagicMock(return_value=new_workspace)

    assert await manager.reload_agent("agent-1") is True

    descriptor = old_workspace._service_manager.descriptors["memory_manager"]
    assert descriptor.reusable is False
    assert (
        "memory_manager" not in old_workspace._service_manager.reused_services
    )
    assert old_workspace.stopped is True


@pytest.mark.asyncio
async def test_reload_reuses_tracker_for_active_stream_reconnect(
    monkeypatch,
) -> None:
    manager = MultiAgentManager()
    config = _config("agent-1")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    old_workspace = _ReloadWorkspace("agent-1")
    new_workspace = _ReloadWorkspace("agent-1")
    manager.agents["agent-1"] = old_workspace
    manager._create_workspace = MagicMock(return_value=new_workspace)
    release = asyncio.Event()
    emitted = asyncio.Event()

    async def producer(_payload):
        yield "data: replayed\n\n"
        emitted.set()
        await release.wait()
        yield "data: live\n\n"

    original_queue, _ = await old_workspace.task_tracker.attach_or_start(
        "chat-1",
        None,
        producer,
        owner=old_workspace,
    )
    await asyncio.wait_for(emitted.wait(), timeout=1)
    await asyncio.sleep(0)

    assert await manager.reload_agent("agent-1") is True
    assert manager.agents["agent-1"] is new_workspace
    assert new_workspace.task_tracker is old_workspace.task_tracker

    reconnect_queue = await new_workspace.task_tracker.attach("chat-1")
    assert reconnect_queue is not None
    assert await reconnect_queue.get() == "data: replayed\n\n"
    assert await reconnect_queue.get() == REPLAY_END_SSE

    cleanup_tasks = list(manager._cleanup_tasks)
    assert cleanup_tasks
    release.set()
    assert await reconnect_queue.get() == "data: live\n\n"
    assert await reconnect_queue.get() is None
    async for _ in old_workspace.task_tracker.stream_from_queue(
        original_queue,
        "chat-1",
    ):
        pass
    await asyncio.wait_for(
        asyncio.gather(*cleanup_tasks),
        timeout=1,
    )
    assert old_workspace.stopped is True


@pytest.mark.asyncio
async def test_cleanup_keeps_old_workspace_alive_after_wait_timeout() -> None:
    manager = MultiAgentManager()
    old_workspace = _ReloadWorkspace("agent-1")
    task = asyncio.Future()
    old_workspace.task_tracker.wait_tasks_done = AsyncMock(
        side_effect=[False, True],
    )

    await manager._graceful_stop_old_instance(
        old_workspace,
        "agent-1",
        active_tasks={"chat-1": task},
    )
    cleanup_tasks = list(manager._cleanup_tasks)
    assert cleanup_tasks
    await asyncio.wait_for(
        asyncio.gather(*cleanup_tasks),
        timeout=1,
    )

    assert old_workspace.task_tracker.wait_tasks_done.await_count == 2
    assert old_workspace.stopped is True


@pytest.mark.asyncio
async def test_cleanup_forces_stop_after_maximum_wait_rounds(
    monkeypatch,
) -> None:
    manager = MultiAgentManager()
    old_workspace = _ReloadWorkspace("agent-1")
    task = asyncio.Future()
    old_workspace.task_tracker.wait_tasks_done = AsyncMock(
        return_value=False,
    )
    monkeypatch.setattr(
        multi_agent_manager_module,
        "_OLD_WORKSPACE_TASK_MAX_WAIT_ROUNDS",
        2,
    )

    await manager._graceful_stop_old_instance(
        old_workspace,
        "agent-1",
        active_tasks={"chat-1": task},
    )
    cleanup_tasks = list(manager._cleanup_tasks)
    assert cleanup_tasks
    await asyncio.wait_for(
        asyncio.gather(*cleanup_tasks),
        timeout=1,
    )

    assert old_workspace.task_tracker.wait_tasks_done.await_count == 2
    assert old_workspace.stopped is True


def _read_custom_startup_concurrency(
    value: str | None = None,
) -> int:
    """Read the import-time setting in an isolated interpreter."""
    env = os.environ.copy()
    env.pop(constants.CUSTOM_AGENT_STARTUP_CONCURRENCY_ENV, None)
    if value is not None:
        env[constants.CUSTOM_AGENT_STARTUP_CONCURRENCY_ENV] = value

    code = (
        "from qwenpaw.constant import "
        "CUSTOM_AGENT_STARTUP_CONCURRENCY; "
        "print(CUSTOM_AGENT_STARTUP_CONCURRENCY)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return int(completed.stdout.strip())


@pytest.mark.asyncio
async def test_disabled_agent_is_not_started_or_mutated(monkeypatch) -> None:
    """Startup must preserve and skip an explicitly disabled profile."""
    manager = MultiAgentManager()
    config = _config("default", "disabled")
    config.agents.profiles["disabled"].enabled = False
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    manager.get_agent = AsyncMock(return_value=SimpleNamespace())

    result = await manager.start_all_configured_agents()

    assert result == {"default": True}
    manager.get_agent.assert_awaited_once_with("default")
    assert config.agents.profiles["disabled"].enabled is False
    assert (
        manager.get_agent_startup_status(
            "disabled",
            enabled=False,
        )
        == AgentStartupStatus.DISABLED
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 5), ("invalid", 5), ("0", 1), ("4", 4)],
)
def test_custom_startup_concurrency_parsing(
    value: str | None,
    expected: int,
) -> None:
    assert _read_custom_startup_concurrency(value=value) == expected


@pytest.mark.asyncio
async def test_core_agents_overlap_before_custom_agents(
    monkeypatch,
) -> None:
    manager = MultiAgentManager()
    config = _config("default", BUILTIN_QA_AGENT_ID, "custom")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )

    core_started = set()
    both_core_started = asyncio.Event()
    release_core = asyncio.Event()
    custom_started = asyncio.Event()

    async def get_agent(agent_id: str):
        if agent_id in {"default", BUILTIN_QA_AGENT_ID}:
            core_started.add(agent_id)
            if len(core_started) == 2:
                both_core_started.set()
            await release_core.wait()
        else:
            custom_started.set()
        return SimpleNamespace()

    manager.get_agent = AsyncMock(side_effect=get_agent)
    callback = MagicMock()
    task = asyncio.create_task(
        manager.start_all_configured_agents(
            on_core_ready=callback,
        ),
    )

    await asyncio.wait_for(both_core_started.wait(), timeout=1)
    assert not custom_started.is_set()
    release_core.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert result == {
        "default": True,
        BUILTIN_QA_AGENT_ID: True,
        "custom": True,
    }
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_core_ready_waits_for_enabled_qa(monkeypatch) -> None:
    """Ready is published only after both enabled core agents finish."""
    manager = MultiAgentManager()
    config = _config("default", BUILTIN_QA_AGENT_ID)
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    default_done = asyncio.Event()
    qa_started = asyncio.Event()
    release_qa = asyncio.Event()

    async def get_agent(agent_id: str):
        if agent_id == "default":
            default_done.set()
        else:
            qa_started.set()
            await release_qa.wait()
        return SimpleNamespace()

    manager.get_agent = AsyncMock(side_effect=get_agent)
    callback = MagicMock()
    task = asyncio.create_task(
        manager.start_all_configured_agents(on_core_ready=callback),
    )

    await asyncio.wait_for(default_done.wait(), timeout=1)
    await asyncio.wait_for(qa_started.wait(), timeout=1)
    callback.assert_not_called()

    release_qa.set()
    await asyncio.wait_for(task, timeout=1)
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_core_ready_does_not_wait_for_disabled_qa(monkeypatch) -> None:
    """A disabled QA agent is excluded from the core readiness phase."""
    manager = MultiAgentManager()
    config = _config("default", BUILTIN_QA_AGENT_ID)
    config.agents.profiles[BUILTIN_QA_AGENT_ID].enabled = False
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    manager.get_agent = AsyncMock(return_value=SimpleNamespace())
    callback = MagicMock()

    result = await manager.start_all_configured_agents(
        on_core_ready=callback,
    )

    assert result == {"default": True}
    manager.get_agent.assert_awaited_once_with("default")
    callback.assert_called_once_with({"default": True})


@pytest.mark.asyncio
async def test_startup_preserves_loaded_agent_status_during_core_phase(
    monkeypatch,
) -> None:
    """A lazily loaded agent remains running while core agents start."""
    manager = MultiAgentManager()
    config = _config("default", "custom")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    manager.agents["custom"] = SimpleNamespace()
    core_started = asyncio.Event()
    release_core = asyncio.Event()

    async def get_agent(agent_id: str):
        if agent_id == "default":
            core_started.set()
            await release_core.wait()
        return manager.agents.get(agent_id, SimpleNamespace())

    manager.get_agent = AsyncMock(side_effect=get_agent)
    task = asyncio.create_task(manager.start_all_configured_agents())

    await asyncio.wait_for(core_started.wait(), timeout=1)
    assert manager.get_agent_startup_status("custom") == (
        AgentStartupStatus.RUNNING
    )
    assert not manager.is_agent_startup_in_progress("custom")

    release_core.set()
    result = await asyncio.wait_for(task, timeout=1)
    assert result == {"default": True, "custom": True}


@pytest.mark.asyncio
async def test_custom_agent_startup_respects_concurrency(
    monkeypatch,
) -> None:
    custom_ids = [f"custom-{index}" for index in range(6)]
    config = _config("default", BUILTIN_QA_AGENT_ID, *custom_ids)
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    monkeypatch.setenv(
        "QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY",
        "2",
    )
    monkeypatch.setattr(
        multi_agent_manager_module,
        "CUSTOM_AGENT_STARTUP_CONCURRENCY",
        2,
    )
    manager = MultiAgentManager()

    active_custom = 0
    peak_custom = 0

    async def get_agent(agent_id: str):
        nonlocal active_custom, peak_custom
        if agent_id in custom_ids:
            active_custom += 1
            peak_custom = max(peak_custom, active_custom)
            await asyncio.sleep(0.01)
            active_custom -= 1
        return SimpleNamespace()

    manager.get_agent = AsyncMock(side_effect=get_agent)
    startup_display = MagicMock()
    result = await manager.start_all_configured_agents(
        startup_display=startup_display,
    )

    assert all(result.values())
    assert peak_custom == 2
    startup_display.start_custom_agents.assert_called_once_with(6)
    assert startup_display.advance.call_count == 6


@pytest.mark.asyncio
async def test_runtime_startups_share_concurrency_and_pending_state(
    monkeypatch,
) -> None:
    """Runtime-created agents use the same bounded startup scheduler."""
    monkeypatch.setattr(
        multi_agent_manager_module,
        "CUSTOM_AGENT_STARTUP_CONCURRENCY",
        1,
    )
    manager = MultiAgentManager()
    config = _config("alpha", "beta")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    alpha_started = asyncio.Event()
    release_alpha = asyncio.Event()
    beta_started = asyncio.Event()

    async def get_agent(agent_id: str):
        if agent_id == "alpha":
            alpha_started.set()
            await release_alpha.wait()
        else:
            beta_started.set()
        return SimpleNamespace()

    manager.get_agent = AsyncMock(side_effect=get_agent)

    alpha_task = manager.schedule_agent_startup("alpha")
    beta_task = manager.schedule_agent_startup("beta")
    await asyncio.wait_for(alpha_started.wait(), timeout=1)

    assert manager.get_agent_startup_status("beta") == (
        AgentStartupStatus.PENDING
    )
    assert manager.is_agent_startup_in_progress("beta")
    assert not beta_started.is_set()

    release_alpha.set()
    await asyncio.wait_for(beta_started.wait(), timeout=1)
    assert await asyncio.gather(alpha_task, beta_task) == [True, True]
    await asyncio.sleep(0)
    assert not manager._agent_startup_tasks


@pytest.mark.asyncio
async def test_startup_display_skips_empty_custom_phase(monkeypatch) -> None:
    manager = MultiAgentManager()
    config = _config("default", BUILTIN_QA_AGENT_ID)
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    manager.get_agent = AsyncMock(return_value=SimpleNamespace())
    startup_display = MagicMock()

    result = await manager.start_all_configured_agents(
        startup_display=startup_display,
    )

    assert all(result.values())
    startup_display.start_custom_agents.assert_not_called()
    startup_display.advance.assert_not_called()


@pytest.mark.asyncio
async def test_default_failure_skips_custom_agent_phase(monkeypatch) -> None:
    """Custom agents must not start when the Default core agent fails."""
    manager = MultiAgentManager()
    config = _config("default", "custom")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )

    async def get_agent(agent_id: str):
        if agent_id == "default":
            raise RuntimeError("invalid default config")
        return SimpleNamespace()

    manager.get_agent = AsyncMock(side_effect=get_agent)
    startup_display = MagicMock()

    result = await manager.start_all_configured_agents(
        startup_display=startup_display,
    )

    assert result == {"default": False, "custom": False}
    manager.get_agent.assert_awaited_once_with("default")
    startup_display.start_custom_agents.assert_not_called()
    startup_display.advance.assert_not_called()


class _WorkspaceStub:
    def __init__(self, start_event: asyncio.Event, release: asyncio.Event):
        self._start_event = start_event
        self._release = release

    async def start(self) -> None:
        self._start_event.set()
        await self._release.wait()

    def set_manager(self, _manager) -> None:
        return None


@pytest.mark.asyncio
async def test_get_agent_updates_runtime_status(monkeypatch) -> None:
    manager = MultiAgentManager()
    config = _config("custom")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    workspace = _WorkspaceStub(started, release)
    monkeypatch.setattr(
        manager,
        "_create_workspace",
        lambda **_kwargs: workspace,
    )

    task = asyncio.create_task(manager.get_agent("custom"))
    await asyncio.wait_for(started.wait(), timeout=1)
    assert manager.get_agent_startup_status("custom") == (
        AgentStartupStatus.STARTING
    )

    release.set()
    assert await asyncio.wait_for(task, timeout=1) is workspace
    assert manager.get_agent_startup_status("custom") == (
        AgentStartupStatus.RUNNING
    )


@pytest.mark.asyncio
async def test_cancelled_start_cleans_pending_state(monkeypatch) -> None:
    manager = MultiAgentManager()
    config = _config("custom")
    monkeypatch.setattr(
        "qwenpaw.app.multi_agent_manager.load_config",
        lambda: config,
    )
    started = asyncio.Event()
    never_release = asyncio.Event()
    workspace = _WorkspaceStub(started, never_release)
    monkeypatch.setattr(
        manager,
        "_create_workspace",
        lambda **_kwargs: workspace,
    )

    task = asyncio.create_task(manager.get_agent("custom"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "custom" not in manager._pending_starts
    assert manager.get_agent_startup_status("custom") == (
        AgentStartupStatus.FAILED
    )
