# -*- coding: utf-8 -*-
"""Tests for per-agent model configuration."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from copaw.config.config import (
    AgentProfileConfig,
    AgentsRunningConfig,
    load_agent_config,
    save_agent_config,
)
from copaw.constant import (
    LLM_BACKOFF_BASE,
    LLM_BACKOFF_CAP,
    LLM_MAX_RETRIES,
)
from copaw.providers.models import ModelSlotConfig


@pytest.fixture
def mock_agent_workspace(tmp_path, monkeypatch):
    """Create a temporary agent workspace for testing."""
    import json
    from copaw.config.utils import get_config_path
    from copaw.config.config import Config, AgentsConfig, AgentProfileRef

    # Setup workspace directory
    workspace_dir = tmp_path / "workspaces" / "test_agent"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Patch config path FIRST before any config operations
    monkeypatch.setenv(
        "COPAW_CONFIG_PATH",
        str(tmp_path / "config.json"),
    )

    # Create root config with this agent
    root_config = Config(
        agents=AgentsConfig(
            active_agent="test_agent",
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
        json.dump(root_config.model_dump(exclude_none=True), f)

    # Now create agent.json
    agent_config = AgentProfileConfig(
        id="test_agent",
        name="Test Agent",
        description="Test agent for model config",
    )
    save_agent_config("test_agent", agent_config)

    return workspace_dir


def test_agent_model_config_defaults_to_none(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name,unused-argument
    """Test that agent model config defaults to None."""
    agent_config = load_agent_config("test_agent")
    assert agent_config.active_model is None


def test_agent_model_config_can_be_set(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name,unused-argument
    """Test setting agent-specific model config."""
    agent_config = load_agent_config("test_agent")

    # Set active model
    agent_config.active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-4",
    )
    save_agent_config("test_agent", agent_config)

    # Reload and verify
    reloaded_config = load_agent_config("test_agent")
    assert reloaded_config.active_model is not None
    assert reloaded_config.active_model.provider_id == "openai"
    assert reloaded_config.active_model.model == "gpt-4"


def test_agent_model_config_persists_across_reloads(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name,unused-argument
    """Test that model config persists across multiple save/load cycles."""
    agent_config = load_agent_config("test_agent")

    # Set model
    agent_config.active_model = ModelSlotConfig(
        provider_id="anthropic",
        model="claude-3-5-sonnet-20241022",
    )
    save_agent_config("test_agent", agent_config)

    # Reload multiple times
    for _ in range(3):
        reloaded = load_agent_config("test_agent")
        assert reloaded.active_model is not None
        assert reloaded.active_model.provider_id == "anthropic"
        assert reloaded.active_model.model == "claude-3-5-sonnet-20241022"


def test_agent_model_config_can_be_cleared(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name,unused-argument
    """Test that model config can be set to None."""
    agent_config = load_agent_config("test_agent")

    # Set a model
    agent_config.active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-4",
    )
    save_agent_config("test_agent", agent_config)

    # Clear it
    agent_config.active_model = None
    save_agent_config("test_agent", agent_config)

    # Verify it's cleared
    reloaded = load_agent_config("test_agent")
    assert reloaded.active_model is None


def test_different_agents_have_independent_models(tmp_path, monkeypatch):
    """Test that different agents can have different model configs."""
    # Patch config path
    monkeypatch.setenv(
        "COPAW_CONFIG_PATH",
        str(tmp_path / "config.json"),
    )

    # Create two agents
    import json
    from copaw.config.config import (
        Config,
        AgentsConfig,
        AgentProfileRef,
    )
    from copaw.config.utils import get_config_path

    agent1_dir = tmp_path / "workspaces" / "agent1"
    agent2_dir = tmp_path / "workspaces" / "agent2"
    agent1_dir.mkdir(parents=True, exist_ok=True)
    agent2_dir.mkdir(parents=True, exist_ok=True)

    # Create root config
    root_config = Config(
        agents=AgentsConfig(
            active_agent="agent1",
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
        json.dump(root_config.model_dump(exclude_none=True), f)

    # Create agent configs
    config1 = AgentProfileConfig(
        id="agent1",
        name="Agent 1",
    )
    config2 = AgentProfileConfig(
        id="agent2",
        name="Agent 2",
    )

    # Set different models
    config1.active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-4",
    )
    config2.active_model = ModelSlotConfig(
        provider_id="anthropic",
        model="claude-3-5-sonnet-20241022",
    )

    save_agent_config("agent1", config1)
    save_agent_config("agent2", config2)

    # Verify they're independent
    reloaded1 = load_agent_config("agent1")
    reloaded2 = load_agent_config("agent2")

    assert reloaded1.active_model.provider_id == "openai"
    assert reloaded1.active_model.model == "gpt-4"

    assert reloaded2.active_model.provider_id == "anthropic"
    assert reloaded2.active_model.model == "claude-3-5-sonnet-20241022"


def test_model_config_excluded_when_none(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name
    """Test that active_model is excluded from agent.json when None."""
    agent_config = load_agent_config("test_agent")
    agent_config.active_model = None
    save_agent_config("test_agent", agent_config)

    # Read the raw JSON file
    import json

    agent_json_path = mock_agent_workspace / "agent.json"
    with open(agent_json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # active_model should not be in the JSON
    assert "active_model" not in raw_data


def test_model_config_included_when_set(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name
    """Test that active_model is included in agent.json when set."""
    agent_config = load_agent_config("test_agent")
    agent_config.active_model = ModelSlotConfig(
        provider_id="openai",
        model="gpt-4-turbo",
    )
    save_agent_config("test_agent", agent_config)

    # Read the raw JSON file
    import json

    agent_json_path = mock_agent_workspace / "agent.json"
    with open(agent_json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # active_model should be in the JSON
    assert "active_model" in raw_data
    assert raw_data["active_model"]["provider_id"] == "openai"
    assert raw_data["active_model"]["model"] == "gpt-4-turbo"


def test_agent_running_config_has_llm_retry_defaults(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name,unused-argument
    """Test that agent running config exposes LLM retry defaults."""
    agent_config = load_agent_config("test_agent")

    assert agent_config.running.llm_retry_enabled is (LLM_MAX_RETRIES > 0)
    assert agent_config.running.llm_max_retries == max(LLM_MAX_RETRIES, 1)
    assert agent_config.running.llm_backoff_base == LLM_BACKOFF_BASE
    assert agent_config.running.llm_backoff_cap == LLM_BACKOFF_CAP


def test_agent_running_config_llm_retry_persists(
    mock_agent_workspace,
):  # pylint: disable=redefined-outer-name,unused-argument
    """Test that LLM retry settings persist in agent.json."""
    agent_config = load_agent_config("test_agent")
    agent_config.running = AgentsRunningConfig(
        llm_retry_enabled=False,
        llm_max_retries=5,
        llm_backoff_base=0.5,
        llm_backoff_cap=8.0,
    )
    save_agent_config("test_agent", agent_config)

    reloaded_config = load_agent_config("test_agent")

    assert reloaded_config.running.llm_retry_enabled is False
    assert reloaded_config.running.llm_max_retries == 5
    assert reloaded_config.running.llm_backoff_base == 0.5
    assert reloaded_config.running.llm_backoff_cap == 8.0


def test_agent_running_config_rejects_backoff_cap_below_base():
    """Test that backoff cap cannot be lower than backoff base."""
    with pytest.raises(ValidationError):
        AgentsRunningConfig(
            llm_backoff_base=2.0,
            llm_backoff_cap=1.0,
        )
