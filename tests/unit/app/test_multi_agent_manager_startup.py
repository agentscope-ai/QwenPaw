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
from qwenpaw.constant import BUILTIN_QA_AGENT_ID


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


def _read_custom_startup_concurrency(
    value: str | None = None,
    legacy_value: str | None = None,
) -> int:
    """Read the import-time setting in an isolated interpreter."""
    env = os.environ.copy()
    env.pop(constants.CUSTOM_AGENT_STARTUP_CONCURRENCY_ENV, None)
    legacy_env = "COPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY"
    env.pop(legacy_env, None)
    if value is not None:
        env[constants.CUSTOM_AGENT_STARTUP_CONCURRENCY_ENV] = value
    if legacy_value is not None:
        env[legacy_env] = legacy_value

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


def test_custom_startup_concurrency_supports_legacy_env() -> None:
    """The legacy COPAW-prefixed environment variable remains supported."""
    assert _read_custom_startup_concurrency(legacy_value="3") == 3


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
