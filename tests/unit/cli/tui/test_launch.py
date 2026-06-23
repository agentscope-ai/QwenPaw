# -*- coding: utf-8 -*-
"""Tests for launching the bundled TUI (`qwenpaw` / `qwenpaw tui`).

Replaces paw's old ``test_cli.py`` + ``test_resolve.py``: the standalone
``paw`` command and PATH-based resolution were dropped when the TUI moved into
QwenPaw. The TUI now spawns ``qwenpaw acp`` using the *current* interpreter.
"""

from __future__ import annotations

# Tests assert on transport internals and use a stub run_tui.
# pylint: disable=protected-access,unused-argument

import sys

import pytest

from click.testing import CliRunner

from qwenpaw.cli.tui.launch import _build_transport, tui_cmd

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def test_default_transport_targets_current_interpreter():
    """Default spawns this very ``python -m qwenpaw acp`` (no PATH lookup)."""
    transport, description = _build_transport(agent=None, resume=None)
    assert transport._command == [
        sys.executable,
        "-m",
        "qwenpaw",
        "acp",
        "--local-diagnostics",
    ]
    assert "qwenpaw acp" in description
    assert "--local-diagnostics" in description


def test_default_transport_appends_agent_once():
    """``--agent`` is appended exactly once (by the transport)."""
    transport, _ = _build_transport(agent="writer", resume=None)
    assert transport._command == [
        sys.executable,
        "-m",
        "qwenpaw",
        "acp",
        "--local-diagnostics",
        "--agent",
        "writer",
    ]


def test_resume_is_threaded_through():
    transport, _ = _build_transport(agent=None, resume="sess-123")
    assert transport._resume_session_id == "sess-123"


def test_tui_help():
    result = CliRunner().invoke(tui_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output
    assert "--resume" in result.output


def test_tui_cmd_invokes_run_tui(monkeypatch):
    calls = {}

    def fake_run_tui(*, agent, resume):
        calls["agent"] = agent
        calls["resume"] = resume

    monkeypatch.setattr("qwenpaw.cli.tui.launch.run_tui", fake_run_tui)
    result = CliRunner().invoke(tui_cmd, ["--agent", "writer"])
    assert result.exit_code == 0
    assert calls == {
        "agent": "writer",
        "resume": None,
    }


def test_bare_qwenpaw_launches_tui(monkeypatch):
    """Bare ``qwenpaw`` (no subcommand) opens the TUI."""
    from qwenpaw.cli.main import cli

    launched = {"called": False}

    def fake_run_tui(*args, **kwargs):
        launched["called"] = True

    monkeypatch.setattr("qwenpaw.cli.tui.launch.run_tui", fake_run_tui)
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert launched["called"] is True
