# -*- coding: utf-8 -*-
"""Trusted request-scoped project directory overrides."""

from __future__ import annotations

# Tests target request-scope helpers directly.
# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.services.session_config import resolve_runtime_parameters
from qwenpaw.modes.mission.state import write_loop_config


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


@pytest.mark.asyncio
async def test_restored_mission_pins_the_runtime_project_before_build(
    tmp_path,
):
    workspace_dir = tmp_path / "workspace"
    project = tmp_path / "mission-project"
    other = tmp_path / "other"
    for directory in (workspace_dir, project, other):
        directory.mkdir()
    mission_dir = tmp_path / "mission"
    mission_dir.mkdir()
    write_loop_config(mission_dir, {"source_project_dir": str(project)})

    async def load(**kwargs):
        kwargs["agent"].load_state_dict(
            {
                "mode_state": {
                    "mission": {
                        "active": True,
                        "loop_dir": str(mission_dir),
                    },
                },
            },
        )

    session = SimpleNamespace(load_session_state=AsyncMock(side_effect=load))
    ctx = SimpleNamespace(
        workspace_dir=workspace_dir,
        agent_id="default",
        session_id="mission",
        mode_state={},
        workspace=SimpleNamespace(session=session),
        request=SimpleNamespace(user_id="user", channel="console"),
    )
    parameters = RuntimeParameters(
        profile=AgentProfileConfig(id="default", name="Default"),
        overrides={"project_dir": str(other)},
    )
    with parameters.scope():
        snapshot, directories = await resolve_runtime_parameters(ctx)
    assert snapshot.config.project_dir == str(project)
    assert directories.primary_path == project
    assert ctx.mode_state["mission"]["active"] is True
    session.load_session_state.assert_awaited_once()
    prompt = AgentBuilder().build_prompt(ctx, snapshot.config)
    assert str(project) in prompt
    assert str(other) not in prompt
