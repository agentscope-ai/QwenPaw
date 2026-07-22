# -*- coding: utf-8 -*-
"""Tests for user-editable Mission defaults."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from qwenpaw.config.config import MissionLoopModeConfig
from qwenpaw.modes.mission.handler import (
    parse_mission_args,
    start_mission,
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
        _, loop_dir = await start_mission(
            task_text="Implement the approved feature",
            workspace_dir=tmp_path,
            agent_id="agent",
            session_id="session",
            verify_commands="pytest -q",
            verification_instructions="Check accessibility manually.",
            max_iterations=14,
            max_retries_per_story=5,
        )

    config = read_loop_config(loop_dir)
    assert config["max_iterations"] == 14
    assert config["max_retries_per_story"] == 5
    assert config["verify_commands"] == "pytest -q"
    assert config["verification_instructions"] == (
        "Check accessibility manually."
    )
