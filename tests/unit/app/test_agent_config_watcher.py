# -*- coding: utf-8 -*-
"""Tests for disk-gated agent configuration reloads."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app import agent_config_watcher as watcher_module
from qwenpaw.config.config import (
    AgentProfileConfig,
    ChannelConfig,
    ConsoleConfig,
)


def _agent_config(*, console_enabled: bool) -> AgentProfileConfig:
    """Build a minimal config with one observable channel setting."""
    return AgentProfileConfig(
        id="agent",
        name="Agent",
        channels=ChannelConfig(
            console=ConsoleConfig(enabled=console_enabled),
        ),
    )


@pytest.mark.asyncio
async def test_watcher_ignores_mutated_cache_without_disk_change(
    tmp_path,
    monkeypatch,
) -> None:
    """An in-memory mutation alone cannot trigger a workspace reload."""
    config_path = tmp_path / "agent.json"
    config_path.write_text("{}", encoding="utf-8")
    config = _agent_config(console_enabled=True)
    manager = SimpleNamespace(reload_agent=AsyncMock())
    workspace = SimpleNamespace(_manager=manager)
    watcher = watcher_module.AgentConfigWatcher(
        "agent",
        tmp_path,
        workspace,
    )
    monkeypatch.setattr(
        watcher_module,
        "load_agent_config",
        lambda _agent_id: config,
    )

    await watcher._snapshot()
    config.channels.console.enabled = False
    await watcher._check()

    manager.reload_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_watcher_reloads_after_disk_and_channel_change(
    tmp_path,
    monkeypatch,
) -> None:
    """A changed file and observable config section trigger a reload."""
    config_path = tmp_path / "agent.json"
    config_path.write_text("{}", encoding="utf-8")
    config = _agent_config(console_enabled=True)
    manager = SimpleNamespace(
        note_agent_config_changed=Mock(),
        reload_agent=AsyncMock(return_value=True),
    )
    workspace = SimpleNamespace(_manager=manager)
    watcher = watcher_module.AgentConfigWatcher(
        "agent",
        tmp_path,
        workspace,
    )
    monkeypatch.setattr(
        watcher_module,
        "load_agent_config",
        lambda _agent_id: config,
    )

    await watcher._snapshot()
    config.channels.console.enabled = False
    config_path.write_text('{"changed": true}', encoding="utf-8")
    await watcher._check()

    manager.note_agent_config_changed.assert_called_once_with("agent")
    manager.reload_agent.assert_awaited_once_with("agent")
