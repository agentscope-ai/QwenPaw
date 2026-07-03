# -*- coding: utf-8 -*-
"""Tests for launching the bundled TUI (`qwenpaw` / `qwenpaw tui`).

Replaces paw's old ``test_cli.py`` + ``test_resolve.py``: the standalone
``paw`` command and PATH-based resolution were dropped when the TUI moved into
QwenPaw. The TUI now spawns ``qwenpaw acp`` using the *current* interpreter.
"""

from __future__ import annotations

# Tests assert on transport internals and use a stub run_tui.
# pylint: disable=protected-access,unused-argument

import json
import sys

import pytest

from click.testing import CliRunner

from qwenpaw.cli.tui import launch
from qwenpaw.cli.tui.launch import _build_transport, _resolve_workspace_dir
from qwenpaw.cli.tui.launch import _resume_command
from qwenpaw.cli.tui.launch import tui_cmd

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def test_default_transport_targets_current_interpreter(tmp_path, monkeypatch):
    """Default spawns this very ``python -m qwenpaw acp`` (no PATH lookup)."""
    monkeypatch.chdir(tmp_path)
    transport, description = _build_transport(agent=None, resume=None)
    assert transport._command == [
        sys.executable,
        "-m",
        "qwenpaw",
        "acp",
        "--local-diagnostics",
    ]
    project_dir = str(tmp_path.resolve())
    assert transport._cwd == project_dir
    assert transport._project_dir == project_dir
    assert "qwenpaw acp" in description
    assert "--local-diagnostics" in description
    assert f"cwd={project_dir}" in description


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


def test_project_path_threads_into_transport(tmp_path):
    transport, description = _build_transport(
        agent=None,
        resume=None,
        project=str(tmp_path),
    )
    project_dir = str(tmp_path.resolve())
    assert transport._cwd == project_dir
    assert transport._project_dir == project_dir
    assert f"cwd={project_dir}" in description


def test_workspace_dir_resolves_active_agent_from_config(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspaces" / "writer"
    config = {
        "agents": {
            "active_agent": "writer",
            "profiles": {
                "writer": {
                    "id": "writer",
                    "workspace_dir": str(workspace),
                },
            },
        },
    }
    (tmp_path / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    monkeypatch.setattr(launch, "WORKING_DIR", tmp_path)

    assert _resolve_workspace_dir(None) == str(workspace.resolve())


def test_workspace_dir_falls_back_to_requested_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "WORKING_DIR", tmp_path)

    assert _resolve_workspace_dir("writer") == str(
        (tmp_path / "workspaces" / "writer").resolve(),
    )


def test_resume_command_quotes_agent_session_and_project_path(monkeypatch):
    monkeypatch.setattr(launch.sys, "platform", "linux")

    command = _resume_command(
        "sess abc",
        agent="writer",
        project_dir="/tmp/project with spaces",
    )

    assert command == (
        "qwenpaw tui --agent writer --resume 'sess abc' "
        "'/tmp/project with spaces'"
    )


def test_resume_command_uses_windows_quoting(monkeypatch):
    monkeypatch.setattr(launch.sys, "platform", "win32")

    command = _resume_command(
        "sess abc",
        agent=None,
        project_dir=r"C:\Project Dir",
    )

    assert command == r'qwenpaw tui --resume "sess abc" "C:\Project Dir"'


def test_resume_command_quotes_windows_project_path_with_shell_meta(
    monkeypatch,
):
    monkeypatch.setattr(launch.sys, "platform", "win32")

    command = _resume_command(
        "sess-abc",
        agent=None,
        project_dir=r"C:\A&B",
    )

    assert command == r'qwenpaw tui --resume sess-abc "C:\A&B"'


def test_resume_command_quotes_windows_project_path_trailing_backslash(
    monkeypatch,
):
    monkeypatch.setattr(launch.sys, "platform", "win32")

    command = _resume_command(
        "sess-abc",
        agent=None,
        project_dir="C:\\",
    )

    assert command == r'qwenpaw tui --resume sess-abc "C:\\"'


def test_run_tui_prints_resume_hint(monkeypatch, capsys, tmp_path):
    class FakeTransport:
        session_id = "sess-123"
        _project_dir = str(tmp_path)

    class FakeApp:
        def __init__(self, transport, **kwargs):
            self.transport = transport
            self.kwargs = kwargs

        def run(self):
            return None

    monkeypatch.setattr(
        launch,
        "_build_transport",
        lambda **_: (FakeTransport(), "fake transport"),
    )
    monkeypatch.setattr("qwenpaw.cli.tui.app.PawApp", FakeApp)

    launch.run_tui(agent="writer")

    command = _resume_command(
        "sess-123",
        agent="writer",
        project_dir=str(tmp_path),
    )
    assert capsys.readouterr().out == (
        f"Bye! To resume this session, run: {command}\n"
    )


def test_tui_help():
    result = CliRunner().invoke(tui_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--agent" in result.output
    assert "--resume" in result.output
    assert "[PROJECT]" in result.output


def test_tui_cmd_invokes_run_tui(monkeypatch):
    calls = {}

    def fake_run_tui(*, agent, resume, project):
        calls["agent"] = agent
        calls["resume"] = resume
        calls["project"] = project

    monkeypatch.setattr("qwenpaw.cli.tui.launch.run_tui", fake_run_tui)
    result = CliRunner().invoke(tui_cmd, ["--agent", "writer"])
    assert result.exit_code == 0
    assert calls == {
        "agent": "writer",
        "resume": None,
        "project": None,
    }


def test_tui_cmd_accepts_project(monkeypatch, tmp_path):
    calls = {}

    def fake_run_tui(*, agent, resume, project):
        calls["agent"] = agent
        calls["resume"] = resume
        calls["project"] = project

    monkeypatch.setattr("qwenpaw.cli.tui.launch.run_tui", fake_run_tui)
    result = CliRunner().invoke(tui_cmd, [str(tmp_path)])
    assert result.exit_code == 0
    assert calls == {
        "agent": None,
        "resume": None,
        "project": str(tmp_path),
    }


def test_bare_qwenpaw_launches_tui(monkeypatch):
    """Bare ``qwenpaw`` (no subcommand) opens the TUI."""
    from qwenpaw.cli.main import cli

    launched = {}

    def fake_run_tui(*args, **kwargs):
        launched["called"] = True
        launched["kwargs"] = kwargs

    monkeypatch.setattr("qwenpaw.cli.tui.launch.run_tui", fake_run_tui)
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert launched["called"] is True
    assert launched["kwargs"]["project"] is None


def test_bare_qwenpaw_project_launches_tui(monkeypatch):
    """``qwenpaw .`` opens the TUI with the current directory as project."""
    from qwenpaw.cli.main import cli

    launched = {}

    def fake_run_tui(*args, **kwargs):
        launched["called"] = True
        launched["kwargs"] = kwargs

    monkeypatch.setattr("qwenpaw.cli.tui.launch.run_tui", fake_run_tui)
    result = CliRunner().invoke(cli, ["."])
    assert result.exit_code == 0
    assert launched["called"] is True
    assert launched["kwargs"]["project"] == "."


def test_bare_qwenpaw_unknown_command_still_errors(monkeypatch):
    """Only path-like unknown args are treated as TUI project paths."""
    from qwenpaw.cli.main import cli

    monkeypatch.setattr(
        "qwenpaw.cli.tui.launch.run_tui",
        pytest.fail,
    )
    result = CliRunner().invoke(cli, ["__missing_qwenpaw_command__"])
    assert result.exit_code != 0
    assert "No such command" in result.output
