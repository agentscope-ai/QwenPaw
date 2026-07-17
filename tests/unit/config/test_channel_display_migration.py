# -*- coding: utf-8 -*-
"""Tests for the one-shot channel display migration."""

import json
from threading import Lock

from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    load_agent_config,
    migrate_channel_display_fields,
)
from qwenpaw.config import utils as config_utils
from qwenpaw.config.utils import _load_and_validate_config


def test_migrate_legacy_hidden_tool_messages():
    channels = {
        "slack": {
            "filter_tool_messages": True,
            "filter_thinking": True,
        },
    }

    assert migrate_channel_display_fields(channels)
    assert channels["slack"] == {
        "show_tool_calls": False,
        "show_tool_results": False,
        "show_thinking": False,
        "tool_call_max_length": 200,
        "tool_result_max_length": 500,
    }


def test_migrate_preserves_explicit_new_fields():
    channels = {
        "slack": {
            "filter_tool_messages": False,
            "show_tool_calls": False,
            "tool_call_max_length": 0,
        },
    }

    assert migrate_channel_display_fields(channels)
    assert channels["slack"]["show_tool_calls"] is False
    assert channels["slack"]["show_tool_results"] is True
    assert channels["slack"]["tool_call_max_length"] == 0
    assert channels["slack"]["tool_result_max_length"] == 500
    assert channels["slack"]["show_thinking"] is True


def test_root_config_migration_persists(tmp_path):
    config_path = tmp_path / "config.json"
    raw = {
        "channels": {
            "slack": {"filter_tool_messages": True},
        },
    }
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    config = _load_and_validate_config(config_path, raw)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))

    assert config.channels.slack.show_tool_calls is False
    assert "filter_tool_messages" not in persisted["channels"]["slack"]
    assert persisted["channels"]["slack"]["show_tool_calls"] is False


def test_loaded_agent_config_migration_persists(
    tmp_path,
    monkeypatch,
):
    workspace_dir = tmp_path / "workspaces" / "agent"
    workspace_dir.mkdir(parents=True)
    agent_config_path = workspace_dir / "agent.json"
    raw = AgentProfileConfig(id="agent", name="Agent").model_dump(
        exclude_none=True,
    )
    raw["channels"] = {"slack": {"filter_tool_messages": True}}
    agent_config_path.write_text(json.dumps(raw), encoding="utf-8")

    root_config = Config(
        agents=AgentsConfig(
            active_agent="agent",
            profiles={
                "agent": AgentProfileRef(
                    id="agent",
                    workspace_dir=str(workspace_dir),
                ),
            },
        ),
    )
    monkeypatch.setattr(config_utils, "load_config", lambda: root_config)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    monkeypatch.setattr(config_utils, "_agent_config_lock", Lock())

    config = load_agent_config("agent")
    persisted = json.loads(agent_config_path.read_text(encoding="utf-8"))

    assert config.channels.slack.show_tool_calls is False
    assert "filter_tool_messages" not in persisted["channels"]["slack"]
    assert persisted["channels"]["slack"]["show_tool_calls"] is False
