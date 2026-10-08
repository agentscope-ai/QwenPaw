# -*- coding: utf-8 -*-
"""Tests for the ``qwenpaw acp`` CLI command."""
from __future__ import annotations

import pytest

from click.testing import CliRunner

from qwenpaw.cli.acp_cmd import acp_cmd


def test_acp_cmd_passes_local_diagnostics(monkeypatch, tmp_path):
    captured = {}

    def initialize():
        captured[f"initialized"] = True
        print(f"Initialization diagnostic")

    monkeypatch.setattr(
        f"qwenpaw.cli.init_cmd.ensure_local_runtime_initialized",
        initialize,
    )

    async def fake_run_qwenpaw_agent(**kwargs):
        assert captured[f"initialized"]
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

    assert f"Initialization diagnostic" not in result.stdout
    assert f"Initialization diagnostic" in result.stderr


def test_acp_initialization_failure_does_not_start_agent(monkeypatch):
    def initialize():
        raise OSError(f"Workspace is not writable")

    async def start(**_kwargs):
        pytest.fail(f"ACP must not start with an incomplete workspace")

    monkeypatch.setattr(
        f"qwenpaw.cli.init_cmd.ensure_local_runtime_initialized",
        initialize,
    )
    monkeypatch.setattr(
        f"qwenpaw.agents.acp.server.run_qwenpaw_agent",
        start,
    )
    result = CliRunner().invoke(acp_cmd, [])
    assert result.exit_code != 0
    assert isinstance(result.exception, OSError)
