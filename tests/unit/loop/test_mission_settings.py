# -*- coding: utf-8 -*-
"""Tests for user-editable Mission defaults."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.config.config import AgentProfileConfig, MissionLoopModeConfig
from qwenpaw.config.runtime import RuntimeParameters
from qwenpaw.modes.mission import MissionMode
from qwenpaw.modes.mission.handler import (
    parse_mission_args,
)
from qwenpaw.modes.mission.prompts import build_master_prompt
from qwenpaw.modes.mission.state import read_loop_config


def test_mission_config_defaults_and_bounds() -> None:
    """Mission settings expose conservative defaults with validation."""
    config = MissionLoopModeConfig()

    assert config.max_iterations == 20
    assert config.max_retries_per_story == 3
    assert config.default_verification_instructions == ""
    assert config.default_verify_command == ""

    with pytest.raises(ValidationError):
        MissionLoopModeConfig(max_retries_per_story=11)


def test_mission_args_use_defaults_and_allow_command_override() -> None:
    """Per-mission arguments override only values explicitly provided."""
    defaults = parse_mission_args(
        "implement the feature",
        default_max_iterations=12,
        default_verify_command="npm test",
    )
    override = parse_mission_args(
        "implement the feature --max-iterations 7 --verify pytest",
        default_max_iterations=12,
        default_verify_command="npm test",
    )

    assert defaults["max_iterations"] == 12
    assert defaults["verify_commands"] == "npm test"
    assert override["max_iterations"] == 7
    assert override["verify_commands"] == "pytest"


def test_master_prompt_uses_configured_story_retry_limit() -> None:
    """Retry configuration replaces the previous hard-coded prompt value."""
    prompt = build_master_prompt(
        loop_dir="/tmp/mission",
        agent_id="agent",
        max_retries_per_story=6,
    )

    assert "Max 6 retries per story" in prompt
    assert "Max 3 retries per story" not in prompt


def test_master_prompt_includes_verification_instructions() -> None:
    """Verifier receives natural-language guidance separately from commands."""
    prompt = build_master_prompt(
        loop_dir="/tmp/mission",
        agent_id="agent",
        verification_instructions=(
            "Check Windows path handling and inspect the rendered UI."
        ),
        verify_commands="pytest -q",
    )

    assert "Check Windows path handling" in prompt
    assert "**Verify command**: pytest -q" in prompt


@pytest.mark.asyncio
async def test_start_mission_persists_editable_defaults(tmp_path) -> None:
    """New missions persist settings used by the existing workflow."""
    git_context = {
        "git_installed": False,
        "is_git_repo": False,
        "default_branch": "",
        "repo_root": "",
    }
    with patch(
        "qwenpaw.modes.mission.handler.detect_git_context",
        new=AsyncMock(return_value=git_context),
    ):
        mode = MissionMode()
        parameters = RuntimeParameters(
            profile=AgentProfileConfig(id="agent", name="Agent"),
            overrides={
                "running": {
                    "loop": {
                        "mission": {
                            "max_iterations": 14,
                            "max_retries_per_story": 5,
                            "default_verify_command": "pytest -q",
                            "default_verification_instructions": (
                                "Check accessibility manually."
                            ),
                        },
                    },
                },
            },
        )
        ctx = SimpleNamespace(
            workspace_dir=tmp_path / "agent-workspace",
            agent_id="agent",
            session_id="session",
            mode_state={},
            input_msgs=[],
        )
        with parameters.scope(), scoped_session_id(ctx.session_id), patch(
            "qwenpaw.config.context.get_current_project_dir",
            return_value=tmp_path,
        ):
            await mode.commands()[0].handler(
                ctx,
                "Implement the approved feature",
            )
        loop_dir = tmp_path / ctx.mode_state["mission"]["loop_dir"]

    config = read_loop_config(loop_dir)
    assert config["max_iterations"] == 14
    assert config["max_retries_per_story"] == 5
    assert config["verify_commands"] == "pytest -q"
    assert config["verification_instructions"] == (
        "Check accessibility manually."
    )
    assert loop_dir.parent == tmp_path / ".qwenpaw" / "missions"
    assert config["source_project_dir"] == str(tmp_path)
    assert config["workspace_dir"] == str(tmp_path / "agent-workspace")
    assert config["mission_run_dir"] == str(tmp_path)
