# -*- coding: utf-8 -*-
"""Trusted request-scoped project directory overrides."""

from __future__ import annotations

# Tests target request-scope helpers directly.
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_CODING_PROJECT_META_KEY
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.prompt_contributors import CodingModeContributor


def test_request_project_override_does_not_enable_coding_tools(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {ACP_CODING_PROJECT_META_KEY: str(tmp_path)},
    )

    assert updated is not config
    assert updated.coding_mode.enabled is False
    assert updated.project_dir == str(tmp_path.resolve())
    assert config.coding_mode.enabled is False
    assert config.project_dir is None


def test_session_project_override_uses_canonical_request_key(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {"project_dir": str(tmp_path)},
    )

    assert updated is not config
    assert updated.project_dir == str(tmp_path.resolve())
    assert updated.coding_mode.enabled is False


def test_active_mode_project_precedes_session_project(tmp_path):
    active_dir = tmp_path / "active"
    session_dir = tmp_path / "session"
    active_dir.mkdir()
    session_dir.mkdir()
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {
            "active_mode_project_dir": str(active_dir),
            "project_dir": str(session_dir),
        },
    )

    assert updated.project_dir == str(active_dir.resolve())


def test_request_coding_project_ignores_non_directory(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")

    updated = AgentBuilder._apply_request_project(
        config,
        {ACP_CODING_PROJECT_META_KEY: str(tmp_path / "missing")},
    )

    assert updated is config
    assert config.coding_mode.enabled is False


@pytest.mark.usefixtures("capture_qwenpaw_logs")
def test_request_coding_project_warns_for_unsupported_config(
    caplog,
    tmp_path,
):
    config = {}

    updated = AgentBuilder._apply_request_project(
        config,
        {ACP_CODING_PROJECT_META_KEY: str(tmp_path)},
    )

    assert updated is config
    assert "unsupported config type: dict" in caplog.text


def test_coding_prompt_prefers_request_project(monkeypatch, tmp_path):
    config = AgentProfileConfig(id="default", name="Default")
    config.coding_mode.enabled = True
    config.project_dir = str(tmp_path)

    def fail_load_agent_config(_agent_id):
        raise AssertionError("request project should be used first")

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        fail_load_agent_config,
    )

    assert CodingModeContributor._resolve_project_dir(config) == str(tmp_path)


def test_normal_prompt_includes_workspace_fallback_as_project(tmp_path):
    config = AgentProfileConfig(id="default", name="Default")
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        agent_id="default",
        session_id="session-1",
        request=SimpleNamespace(
            user_id="user-1",
            channel="console",
            request_context={},
        ),
        workspace=None,
    )

    prompt = AgentBuilder().build_prompt(ctx, config)

    assert "Project directory" in prompt
    assert str(tmp_path) in prompt
    assert "Working directory:" not in prompt


def test_normal_prompt_uses_session_project_snapshot(tmp_path):
    workspace_dir = tmp_path / "workspace"
    project_dir = tmp_path / "project"
    workspace_dir.mkdir()
    project_dir.mkdir()
    config = AgentProfileConfig(id="default", name="Default")
    config = AgentBuilder._apply_request_project(
        config,
        {"project_dir": str(project_dir)},
    )
    ctx = SimpleNamespace(
        workspace_dir=workspace_dir,
        agent_id="default",
        session_id="session-1",
        request=SimpleNamespace(
            user_id="user-1",
            channel="console",
            request_context={"project_dir": str(project_dir)},
        ),
        workspace=None,
    )

    prompt = AgentBuilder().build_prompt(ctx, config)

    assert str(project_dir) in prompt
    assert str(workspace_dir) in prompt
    assert "Agent workspace (internal" in prompt
