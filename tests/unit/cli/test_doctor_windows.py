# -*- coding: utf-8 -*-
"""Tests for Windows-specific doctor diagnostics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from qwenpaw.cli import doctor_checks


def test_windows_environment_lines_skips_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(doctor_checks.platform, "system", lambda: "Linux")

    assert not doctor_checks.windows_environment_lines()


def test_windows_environment_lines_reports_long_paths_and_powershell(
    monkeypatch,
) -> None:
    monkeypatch.setattr(doctor_checks.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        doctor_checks,
        "_windows_long_paths_enabled",
        lambda: (False, None),
    )
    monkeypatch.setattr(
        doctor_checks,
        "WORKING_DIR",
        Path(r"C:\QwenPaw"),
    )

    def fake_which(name):
        if name == "powershell.exe":
            return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        return None

    monkeypatch.setattr(doctor_checks.shutil, "which", fake_which)
    monkeypatch.setattr(
        doctor_checks,
        "_powershell_language_mode",
        lambda _exe: ("FullLanguage", None),
    )

    lines = doctor_checks.windows_environment_lines()

    assert (
        "Long paths: disabled; deeply nested workspaces, skills, "
        "caches, or package installs may fail over 260 characters"
        in lines
    )
    assert "Current working directory length: 10" in lines
    assert "PowerShell: found powershell.exe" in lines
    assert "PowerShell language mode: FullLanguage" in lines


def test_windows_environment_lines_reports_constrained_language(
    monkeypatch,
) -> None:
    monkeypatch.setattr(doctor_checks.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        doctor_checks,
        "_windows_long_paths_enabled",
        lambda: (True, None),
    )
    monkeypatch.setattr(
        doctor_checks,
        "WORKING_DIR",
        Path("C:/" + "a" * 230),
    )

    def fake_which(name):
        if name == "pwsh.exe":
            return r"C:\Program Files\PowerShell\7\pwsh.exe"
        return None

    monkeypatch.setattr(doctor_checks.shutil, "which", fake_which)
    monkeypatch.setattr(
        doctor_checks,
        "_powershell_language_mode",
        lambda _exe: ("ConstrainedLanguage", None),
    )

    lines = doctor_checks.windows_environment_lines()

    assert "Long paths: enabled" in lines
    assert any(
        "close to Windows MAX_PATH" in line
        for line in lines
    )
    assert "PowerShell: found pwsh.exe" in lines
    assert (
        "PowerShell language mode: ConstrainedLanguage; "
        "some scripts may be restricted" in lines
    )


def test_powershell_language_mode_handles_errors(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="blocked")

    monkeypatch.setattr(doctor_checks.subprocess, "run", fake_run)

    powershell_language_mode = getattr(
        doctor_checks,
        "_powershell_language_mode",
    )
    mode, error = powershell_language_mode("powershell.exe")

    assert mode is None
    assert error == "blocked"
