# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import os
import sys
from pathlib import Path

from qwenpaw.agents.tools import shell


def test_build_shell_env_honors_persisted_path(monkeypatch) -> None:
    process_path = os.pathsep.join(["/usr/local/bin", "/usr/bin"])
    persisted_path = os.pathsep.join(["/home/user/.local/bin", "$PATH"])
    monkeypatch.setenv("PATH", process_path)
    monkeypatch.setattr(
        shell,
        "load_envs",
        lambda: {
            "PATH": persisted_path,
            "CUSTOM_TOOL_HOME": "/home/user/.local",
        },
    )

    env = shell._build_shell_env()

    path_parts = env["PATH"].split(os.pathsep)
    assert path_parts[0] == str(Path(sys.executable).parent)
    assert path_parts[1] == "/home/user/.local/bin"
    assert "/usr/local/bin" in path_parts
    assert "/usr/bin" in path_parts
    assert env["CUSTOM_TOOL_HOME"] == "/home/user/.local"


def test_build_shell_env_keeps_protected_process_values(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("QWENPAW_WORKING_DIR", "/runtime/workdir")
    monkeypatch.delenv("QWENPAW_SECRET_DIR", raising=False)
    monkeypatch.setattr(
        shell,
        "load_envs",
        lambda: {
            "QWENPAW_WORKING_DIR": "/persisted/workdir",
            "QWENPAW_SECRET_DIR": "/persisted/secret",
        },
    )

    env = shell._build_shell_env()

    assert env["QWENPAW_WORKING_DIR"] == "/runtime/workdir"
    assert "QWENPAW_SECRET_DIR" not in env


def test_build_shell_env_falls_back_to_venv_path(monkeypatch) -> None:
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setattr(shell, "load_envs", lambda: {})

    env = shell._build_shell_env()

    assert env["PATH"] == str(Path(sys.executable).parent)
