# -*- coding: utf-8 -*-
"""Regression tests for the workspace config write-then-read idiom.

``load_agent_config`` hands out detached copies to protect its cache;
``Workspace.config`` must pin one snapshot per instance so the
codebase-wide idiom -- mutate ``workspace.config`` in place, then
``save_agent_config(workspace.config)`` -- persists the patch instead
of silently saving a fresh unpatched copy (the integration failures in
test_channel_config/test_heartbeat reproduced exactly that loss).
"""

# Pytest fixtures intentionally provide setup-only arguments to tests.
# pylint: disable=redefined-outer-name,unused-argument,protected-access

from pathlib import Path

import pytest

from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    HeartbeatConfig,
    load_agent_config,
    save_agent_config,
)


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch):
    """Point config persistence and both caches at one temporary tree."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_utils, "get_config_path", lambda: config_path)
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    return config_path


@pytest.fixture
def isolated_agent(isolated_config, tmp_path: Path) -> Path:
    """Create one root profile and persisted agent configuration."""
    workspace = tmp_path / "workspaces" / "agent"
    workspace.mkdir(parents=True)
    root = Config(
        agents=AgentsConfig(
            profiles={
                "agent": AgentProfileRef(
                    id="agent",
                    workspace_dir=str(workspace),
                ),
            },
        ),
    )
    config_utils.save_config(root)
    save_agent_config(
        "agent",
        AgentProfileConfig(
            id="agent",
            name="Agent",
            description="original",
        ),
    )
    return workspace


def _pinned_workspace(workspace_dir: Path) -> Workspace:
    """Build a property-only Workspace without running heavy __init__."""
    ws = object.__new__(Workspace)
    ws.agent_id = "agent"
    ws.workspace_dir = workspace_dir
    ws._config = None
    ws._config_mtime = None
    return ws


def test_config_property_is_stable_between_accesses(isolated_agent):
    ws = _pinned_workspace(isolated_agent)
    assert ws.config is ws.config


def test_patch_then_save_idiom_persists(isolated_agent):
    """The exact PUT-endpoint idiom must survive the loader's copies."""
    ws = _pinned_workspace(isolated_agent)
    ws.config.heartbeat = HeartbeatConfig(enabled=True, every="6h")
    save_agent_config(ws.agent_id, ws.config)

    reloaded = load_agent_config("agent")
    assert reloaded.heartbeat is not None
    assert reloaded.heartbeat.enabled is True
    assert reloaded.heartbeat.every == "6h"

    # A rebuilt workspace (zero-downtime reload) sees the saved value.
    fresh = _pinned_workspace(isolated_agent)
    assert fresh.config.heartbeat.enabled is True


def test_config_property_refreshes_after_external_save(isolated_agent):
    ws = _pinned_workspace(isolated_agent)
    assert ws.config.description == "original"

    external = load_agent_config("agent")
    external.description = "updated-elsewhere"
    save_agent_config("agent", external)

    assert ws.config.description == "updated-elsewhere"


def test_unsaved_mutation_does_not_leak_into_other_instances(
    isolated_agent,
):
    """Loader copies still isolate instances from unsaved edits."""
    ws = _pinned_workspace(isolated_agent)
    ws.config.description = "unsaved"

    other = _pinned_workspace(isolated_agent)
    assert other.config.description == "original"
