# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw acp`` CLI command."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from qwenpaw.cli.acp_cmd import acp_cmd


def test_acp_cmd_passes_local_diagnostics(monkeypatch, tmp_path):
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
        ],
    )

    assert result.exit_code == 0
    assert captured["agent_id"] == "writer"
    assert captured["workspace_dir"] == tmp_path
    assert captured["local_diagnostics"] is True


@pytest.mark.parametrize(
    f"mode_id",
    [f"goal", f"mission", f"custom:quality", f"plugin:review"],
)
def test_acp_cmd_passes_mode(monkeypatch, mode_id):
    captured = {}

    async def fake_run_qwenpaw_agent(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.run_qwenpaw_agent",
        fake_run_qwenpaw_agent,
    )

    result = CliRunner().invoke(
        acp_cmd,
        [f"--mode", mode_id],
    )

    assert result.exit_code == 0
    assert captured[f"mode"] == mode_id


def test_acp_cmd_mode_defaults_to_none(monkeypatch):
    captured = {}

    async def fake_run_qwenpaw_agent(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "qwenpaw.agents.acp.server.run_qwenpaw_agent",
        fake_run_qwenpaw_agent,
    )

    result = CliRunner().invoke(acp_cmd, [])

    assert result.exit_code == 0
    assert captured["mode"] is None
