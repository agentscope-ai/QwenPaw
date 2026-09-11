# -*- coding: utf-8 -*-
"""Integration tests for the QwenPaw CLI surface (coverage sprint 4).

Covers src/qwenpaw/cli/* (CLI & Diagnostics module, 4,390 uncovered
lines, integration coverage 1.9%).

Two tiers:
1. ``--help`` for every registered subcommand (exercises the lazy
   command loader + click wiring, no server needed).
2. Read-only subcommands pointed at the test server via --base-url
   (exercises the HTTP client paths).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_SUBCOMMANDS = [
    "acp",
    "app",
    "hub",
    "channels",
    "channel",
    "daemon",
    "chats",
    "chat",
    "clean",
    "cron",
    "env",
    "init",
    "models",
    "skills",
    "tui",
    "uninstall",
    "desktop",
    "update",
    "shutdown",
    "auth",
    "agents",
    "agent",
    "plugin",
    "task",
    "doctor",
    "auto",
]


def _run_cli(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "qwenpaw", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.integration
@pytest.mark.p1
def test_cli_root_help() -> None:
    """qwenpaw --help lists the command group."""
    proc = _run_cli("--help")
    assert proc.returncode == 0, proc.stderr
    assert "Usage" in proc.stdout


@pytest.mark.integration
@pytest.mark.p1
def test_cli_version() -> None:
    """qwenpaw --version prints the version string."""
    proc = _run_cli("--version")
    assert proc.returncode == 0, proc.stderr
    assert "QwenPaw" in proc.stdout


@pytest.mark.parametrize("sub", _SUBCOMMANDS)
@pytest.mark.integration
@pytest.mark.p1
def test_cli_subcommand_help(sub) -> None:
    """qwenpaw <sub> --help loads the lazy command and shows usage."""
    proc = _run_cli(sub, "--help")
    assert proc.returncode == 0, proc.stderr
    assert "Usage" in proc.stdout


# ------------------------------------------------------------------ #
# read-only subcommands against the live test server
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_cli_agents_list(app_server) -> None:
    """qwenpaw agents list reads the agent list over HTTP."""
    proc = _run_cli(
        "agents",
        "list",
        "--base-url",
        app_server.base_url,
    )
    assert proc.returncode == 0, proc.stderr
    assert "default" in proc.stdout


@pytest.mark.integration
@pytest.mark.p1
def test_cli_cron_list(app_server) -> None:
    """qwenpaw cron list reads cron jobs over HTTP."""
    proc = _run_cli("cron", "list", "--base-url", app_server.base_url)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.p1
def test_cli_channels_list() -> None:
    """qwenpaw channels list reads channel config locally."""
    proc = _run_cli("channels", "list")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.p1
def test_cli_skills_list() -> None:
    """qwenpaw skills list reads the local skill pool."""
    proc = _run_cli("skills", "list")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.p1
def test_cli_models_list() -> None:
    """qwenpaw models list reads provider config locally."""
    proc = _run_cli("models", "list")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.p1
def test_cli_chats_list(app_server) -> None:
    """qwenpaw chats list reads sessions over HTTP."""
    proc = _run_cli("chats", "list", "--base-url", app_server.base_url)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.p1
def test_cli_env_list() -> None:
    """qwenpaw env list prints environment variables (no server)."""
    proc = _run_cli("env", "list")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.integration
@pytest.mark.p1
def test_cli_doctor_runs(
    app_server,  # pylint: disable=unused-argument
) -> None:
    """qwenpaw doctor performs read-only diagnostics."""
    proc = _run_cli("doctor", "--timeout", "2", timeout=120)
    # doctor may report warnings but must not crash
    assert proc.returncode in (0, 1), proc.stderr
