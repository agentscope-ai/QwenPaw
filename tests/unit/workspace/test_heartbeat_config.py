# -*- coding: utf-8 -*-
"""Tests for heartbeat config loading (issue #1597).

Verifies that CronManager and heartbeat functions read heartbeat config
from agent-level agent.json, not from root config.json, and that
the legacy get_heartbeat_config() handles null defaults gracefully.
"""
from pathlib import Path
import json

import pytest

from copaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    HeartbeatConfig,
    load_agent_config,
    save_agent_config,
)
from copaw.config.utils import (
    get_config_path,
    get_heartbeat_config,
    load_heartbeat_for_agent,
)


@pytest.fixture
def workspace_with_heartbeat(tmp_path, monkeypatch):
    """Create a workspace where agent.json has heartbeat enabled
    but root config.json has agents.defaults = null.
    """
    monkeypatch.setenv(
        "COPAW_CONFIG_PATH",
        str(tmp_path / "config.json"),
    )

    workspace_dir = tmp_path / "workspaces" / "test_agent"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Root config: agents.defaults is explicitly null
    root_config = Config(
        agents=AgentsConfig(
            active_agent="test_agent",
            defaults=None,
            profiles={
                "test_agent": AgentProfileRef(
                    id="test_agent",
                    workspace_dir=str(workspace_dir),
                ),
            },
        ),
    )
    config_path = Path(get_config_path())
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(root_config.model_dump(mode="json", by_alias=True), f)

    # Agent config: heartbeat enabled with custom interval
    agent_config = AgentProfileConfig(
        id="test_agent",
        name="Test Agent",
        description="Test agent for heartbeat",
        heartbeat=HeartbeatConfig(
            enabled=True,
            every="15m",
            target="main",
        ),
    )
    save_agent_config("test_agent", agent_config)

    return {
        "workspace_dir": workspace_dir,
        "agent_id": "test_agent",
    }


def test_legacy_get_heartbeat_config_null_defaults(
    workspace_with_heartbeat,
):  # pylint: disable=redefined-outer-name
    """Issue #1597: get_heartbeat_config() must not crash when
    agents.defaults is null in root config.
    """
    # This used to raise: AttributeError: 'NoneType' has no attribute 'heartbeat'
    hb = get_heartbeat_config()
    assert isinstance(hb, HeartbeatConfig)
    # Should return default (enabled=False) since root defaults is null
    assert hb.enabled is False


def test_agent_level_heartbeat_config_is_loaded(
    workspace_with_heartbeat,
):  # pylint: disable=redefined-outer-name
    """Heartbeat config should be loaded from agent.json, not root config."""
    agent_id = workspace_with_heartbeat["agent_id"]
    agent_config = load_agent_config(agent_id)

    assert agent_config.heartbeat is not None
    assert agent_config.heartbeat.enabled is True
    assert agent_config.heartbeat.every == "15m"
    assert agent_config.heartbeat.target == "main"


def test_load_heartbeat_for_agent_reads_agent_json(
    workspace_with_heartbeat,
):  # pylint: disable=redefined-outer-name
    """load_heartbeat_for_agent should read from agent.json."""
    agent_id = workspace_with_heartbeat["agent_id"]
    hb = load_heartbeat_for_agent(agent_id)
    assert hb.enabled is True
    assert hb.every == "15m"
    assert hb.target == "main"


def test_load_heartbeat_for_agent_fallback(tmp_path, monkeypatch):
    """load_heartbeat_for_agent should return defaults for missing agents."""
    monkeypatch.setenv(
        "COPAW_CONFIG_PATH",
        str(tmp_path / "config.json"),
    )
    root_config = Config()
    config_path = Path(get_config_path())
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(root_config.model_dump(mode="json", by_alias=True), f)

    hb = load_heartbeat_for_agent("nonexistent")
    assert isinstance(hb, HeartbeatConfig)
    assert hb.enabled is False


def test_cron_manager_reads_agent_config(
    workspace_with_heartbeat,
):  # pylint: disable=redefined-outer-name
    """CronManager._load_heartbeat_config should read from agent.json."""
    from unittest.mock import MagicMock

    from copaw.app.crons.manager import CronManager
    from copaw.app.crons.repo.base import BaseJobRepository

    mock_repo = MagicMock(spec=BaseJobRepository)
    agent_id = workspace_with_heartbeat["agent_id"]

    mgr = CronManager(
        repo=mock_repo,
        runner=MagicMock(),
        channel_manager=MagicMock(),
        agent_id=agent_id,
    )

    hb = mgr._load_heartbeat_config()
    assert hb.enabled is True
    assert hb.every == "15m"
    assert hb.target == "main"


def test_cron_manager_fallback_on_missing_agent(tmp_path, monkeypatch):
    """CronManager should fall back to defaults if agent config is missing."""
    from unittest.mock import MagicMock

    from copaw.app.crons.manager import CronManager
    from copaw.app.crons.repo.base import BaseJobRepository

    monkeypatch.setenv(
        "COPAW_CONFIG_PATH",
        str(tmp_path / "config.json"),
    )

    # Root config with no agents
    root_config = Config()
    config_path = Path(get_config_path())
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(root_config.model_dump(mode="json", by_alias=True), f)

    mock_repo = MagicMock(spec=BaseJobRepository)
    mgr = CronManager(
        repo=mock_repo,
        runner=MagicMock(),
        channel_manager=MagicMock(),
        agent_id="nonexistent_agent",
    )

    # Should not crash, should return default config
    hb = mgr._load_heartbeat_config()
    assert isinstance(hb, HeartbeatConfig)
    assert hb.enabled is False


def test_heartbeat_config_independence_between_agents(tmp_path, monkeypatch):
    """Different agents should have independent heartbeat configs."""
    monkeypatch.setenv(
        "COPAW_CONFIG_PATH",
        str(tmp_path / "config.json"),
    )

    agent1_dir = tmp_path / "workspaces" / "agent1"
    agent2_dir = tmp_path / "workspaces" / "agent2"
    agent1_dir.mkdir(parents=True, exist_ok=True)
    agent2_dir.mkdir(parents=True, exist_ok=True)

    root_config = Config(
        agents=AgentsConfig(
            active_agent="agent1",
            defaults=None,
            profiles={
                "agent1": AgentProfileRef(
                    id="agent1",
                    workspace_dir=str(agent1_dir),
                ),
                "agent2": AgentProfileRef(
                    id="agent2",
                    workspace_dir=str(agent2_dir),
                ),
            },
        ),
    )
    config_path = Path(get_config_path())
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(root_config.model_dump(mode="json", by_alias=True), f)

    save_agent_config(
        "agent1",
        AgentProfileConfig(
            id="agent1",
            name="Agent 1",
            heartbeat=HeartbeatConfig(enabled=True, every="10m"),
        ),
    )
    save_agent_config(
        "agent2",
        AgentProfileConfig(
            id="agent2",
            name="Agent 2",
            heartbeat=HeartbeatConfig(enabled=False, every="1h"),
        ),
    )

    from unittest.mock import MagicMock

    from copaw.app.crons.manager import CronManager
    from copaw.app.crons.repo.base import BaseJobRepository

    mock_repo = MagicMock(spec=BaseJobRepository)

    mgr1 = CronManager(
        repo=mock_repo,
        runner=MagicMock(),
        channel_manager=MagicMock(),
        agent_id="agent1",
    )
    mgr2 = CronManager(
        repo=mock_repo,
        runner=MagicMock(),
        channel_manager=MagicMock(),
        agent_id="agent2",
    )

    hb1 = mgr1._load_heartbeat_config()
    hb2 = mgr2._load_heartbeat_config()

    assert hb1.enabled is True
    assert hb1.every == "10m"
    assert hb2.enabled is False
    assert hb2.every == "1h"
