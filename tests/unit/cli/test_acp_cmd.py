# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw acp`` CLI command."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from qwenpaw.cli.acp_cmd import acp_cmd


@pytest.mark.parametrize(f"budget", [None, -1, 100])
@pytest.mark.parametrize(f"error", [None, RuntimeError(f"transport failed")])
def test_acp_cmd_passes_local_diagnostics(
    monkeypatch,
    tmp_path,
    budget,
    error,
):
    captured = {}

    async def fake_run_qwenpaw_agent(**kwargs):
        captured.update(kwargs)
        if error is not None:
            raise error

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

    assert result.exit_code == (1 if error is not None else 0)
    assert result.exception is error
    assert captured["agent_id"] == "writer"
    assert captured["workspace_dir"] == tmp_path
    assert captured["local_diagnostics"] is True
    assert captured[f"agent_mode"] == f"custom:quality"
    assert captured[f"goal_token_budget"] == (0 if budget is None else budget)
