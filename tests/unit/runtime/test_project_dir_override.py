# -*- coding: utf-8 -*-
"""Trusted request-scoped project directory overrides."""

from __future__ import annotations

# Tests target request-scope helpers directly.
# pylint: disable=protected-access

from types import SimpleNamespace


from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.config.runtime import RuntimeParameters


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
    # Nothing is configured, so project and workspace are the same path.
    # The directory block then names it once as the working directory
    # rather than printing it twice under two labels, which would invite
    # the model to treat internal QwenPaw state as project content.
    assert "Working directory:" in prompt


def test_normal_prompt_uses_session_project_snapshot(tmp_path):
    workspace_dir = tmp_path / "workspace"
    project_dir = tmp_path / "project"
    workspace_dir.mkdir()
    project_dir.mkdir()
    config = AgentProfileConfig(id="default", name="Default")
    config = RuntimeParameters(
        profile=config,
        overrides={"project_dir": str(project_dir)},
    ).config
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
