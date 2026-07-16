# -*- coding: utf-8 -*-
"""Tests for bounded multi-agent startup scheduling."""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.agent_startup import (
    AgentStartupStatus,
    get_custom_agent_startup_concurrency,
)
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
    [(None, 2), ("invalid", 2), ("0", 1), ("4", 4)],
)
def test_custom_startup_concurrency_parsing(
    monkeypatch,
    value: str | None,
    expected: int,
) -> None:
    monkeypatch.delenv(
        "QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY",
        raising=False,
    )
    monkeypatch.delenv(
        "COPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY",
        raising=False,
    )
    if value is not None:
        monkeypatch.setenv(
            "QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY",
            value,
        )

    assert get_custom_agent_startup_concurrency() == expected


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
async def test_custom_agent_startup_respects_concurrency(
    monkeypatch,
) -> None:
    manager = MultiAgentManager()
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
