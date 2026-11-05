# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw acp`` CLI command."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from qwenpaw.cli.acp_cmd import acp_cmd
from qwenpaw.agents.acp.configuration import ACPConfiguration
from qwenpaw.config.config import AgentProfileConfig


@pytest.mark.parametrize(f"budget", [None, -1, 100])
def test_acp_cmd_passes_local_diagnostics(monkeypatch, tmp_path, budget):
    captured = {}

    async def fake_run_qwenpaw_agent(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.run_qwenpaw_agent",
        fake_run_qwenpaw_agent,
    )

    result = CliRunner().invoke(
        acp_cmd,
        [
            "--agent",
            "writer",
            "--workspace",
            str(tmp_path),
            "--local-diagnostics",
            f"--agent-mode",
            f"custom:quality",
            *(
                [f"--goal-token-budget", str(budget)]
                if budget is not None
                else []
            ),
        ],
    )

    assert result.exit_code == 0
    assert captured["agent_id"] == "writer"
    assert captured["workspace_dir"] == tmp_path
    assert captured["local_diagnostics"] is True
    assert captured[f"agent_mode"] == f"custom:quality"
    assert captured["config_overrides"] == {}
    assert captured["goal_token_budget"] == budget
    config = ACPConfiguration(
        AgentProfileConfig(id="writer", name="Writer"),
        captured["config_overrides"],
        workspace_dir=captured["workspace_dir"],
        goal_token_budget=captured["goal_token_budget"],
    ).base
    assert config.workspace_dir == str(tmp_path)
    assert config.running.loop.goal.max_tokens == (budget or 0)


def test_acp_config_assignments_preserve_json_values(monkeypatch):
    captured = {}

    async def fake_run_qwenpaw_agent(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.run_qwenpaw_agent",
        fake_run_qwenpaw_agent,
    )
    result = CliRunner().invoke(
        acp_cmd,
        [
            "--config",
            "running.loop.iteration.enabled=false",
            "--config",
            "running.llm_max_qpm=0",
            "--config",
            "project_dir=null",
            "--config",
            "system_prompt_files=[]",
            "--config",
            "description=ACP instance",
            "--config",
            "running.loop.goal.max_tokens=50",
            "--goal-token-budget",
            "100",
        ],
    )
    assert result.exit_code == 0
    assert captured["config_overrides"] == {
        "running": {
            "loop": {
                "iteration": {"enabled": False},
                "goal": {"max_tokens": 50},
            },
            "llm_max_qpm": 0,
        },
        "project_dir": None,
        "system_prompt_files": [],
        "description": "ACP instance",
    }

    config = ACPConfiguration(
        AgentProfileConfig(id="default", name="Default"),
        captured["config_overrides"],
        goal_token_budget=captured["goal_token_budget"],
    ).base
    assert config.running.loop.goal.max_tokens == 100
    assert config.running.loop.iteration.enabled is False
