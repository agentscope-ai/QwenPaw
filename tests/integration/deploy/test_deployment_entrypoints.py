# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["weldon.sh", "weldon.ps1"])
def test_entrypoint_exposes_required_commands(name: str):
    text = (ROOT / "deploy" / name).read_text(encoding="utf-8")
    for command in ("init", "up", "down", "status", "logs", "backup", "restore"):
        assert command in text
    assert "down -v" not in text
    assert "docker compose" in text


def test_shell_help_uses_external_branding():
    if shutil.which("sh") is None:
        pytest.skip("POSIX shell is verified on Linux CI")
    script = ROOT / "deploy" / "weldon.sh"
    result = subprocess.run(
        ["sh", str(script), "help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "WeldonAgent" not in result.stderr
    assert "qwenpaw" not in result.stdout.lower()


def test_powershell_help_uses_external_branding():
    script = ROOT / "deploy" / "weldon.ps1"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(script), "help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0
    assert "qwenpaw" not in result.stdout.lower()
