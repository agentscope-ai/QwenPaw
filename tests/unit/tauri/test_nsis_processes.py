# -*- coding: utf-8 -*-
"""Test the installer helper with isolated files and simulated processes."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER = REPO_ROOT / "console/src-tauri/nsis/manage-install-processes.ps1"
POWERSHELL = (
    Path(os.environ.get("SystemRoot", "C:/Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL.is_file(),
    reason="Requires Windows PowerShell",
)


@pytest.fixture
def installer(tmp_path):
    root = tmp_path / "安装 % test" / "QwenPaw Desktop"
    root.mkdir(parents=True)
    for relative in (
        "qwenpaw-desktop.exe",
        "binaries/qwenpaw-backend/qwenpaw-backend.exe",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    profile = tmp_path / "profile"
    launcher = profile / ".qwenpaw/bin/qwenpaw-nm-host.bat"
    launcher.parent.mkdir(parents=True)
    records = tmp_path / "processes.json"
    records.write_text("[]", encoding="utf-8")
    stopped = tmp_path / "stopped.txt"
    log = tmp_path / "installer.log"
    wrapper = tmp_path / "run.ps1"
    wrapper.write_text(
        r"""
param($Helper, $InstallDir, $LogPath, $Records, $Stopped, $Scenario, $Action)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$script:stoppedIds = @()
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($Scenario -eq 'query-failure') { throw 'CIM query unavailable' }
    if ($Filter) { return @{ ProcessId = 42; ParentProcessId = 41 } }
    Get-Content -LiteralPath $Records -Raw -Encoding UTF8 |
        ConvertFrom-Json | ForEach-Object { $_ } |
        Where-Object { $script:stoppedIds -notcontains $_.ProcessId }
}
function Stop-Process {
    [CmdletBinding()]
    param([int]$Id, [switch]$Force)
    if ($Scenario -eq 'stop-failure') {
        Write-Error 'Access denied stopping process'
        return
    }
    $script:stoppedIds += $Id
    Add-Content -LiteralPath $Stopped -Value $Id
}
function Wait-Process {
    [CmdletBinding()]
    param([int[]]$Id, [int]$Timeout)
}
& $Helper -InstallDir $InstallDir -NsisProcessId 42 `
    -LogPath $LogPath -Action $Action
exit $LASTEXITCODE
""",
        encoding="utf-8-sig",
    )

    def run(
        *,
        processes=(),
        scenario="normal",
        action="Prepare",
        log_path=log,
    ):
        records.write_text(json.dumps(processes), encoding="utf-8")
        env = os.environ.copy()
        env["USERPROFILE"] = str(profile)
        env["PATH"] = str(POWERSHELL.parents[2])
        return subprocess.run(
            [
                str(POWERSHELL),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(wrapper),
                str(HELPER),
                str(root),
                str(log_path),
                str(records),
                str(stopped),
                scenario,
                action,
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    return root, launcher, log, stopped, run


def process_record(root, relative, pid, command=""):
    path = root / relative
    return {
        "Name": path.name,
        "ProcessId": pid,
        "ExecutablePath": str(path),
        "CommandLine": command,
    }


@pytest.mark.parametrize("existing_install", [False, True])
def test_empty_launcher_does_not_block_preparation(
    installer,
    existing_install,
):
    root, launcher, _, _, run = installer
    if not existing_install:
        (root / "qwenpaw-desktop.exe").unlink()
    launcher.touch()
    launcher.with_suffix(".bat.qwenpaw-maintenance").touch()

    result = run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert launcher.read_bytes() == b""


def test_preparation_and_restore_preserve_launcher(installer):
    root, launcher, _, _, run = installer
    original = f'@echo off\r\n"{root}\\python.exe" host.py\r\n'.encode(
        "utf-8-sig",
    )
    launcher.write_bytes(original)

    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert b"QWENPAW_INSTALL_MAINTENANCE" in launcher.read_bytes()

    result = run(action="Restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert launcher.read_bytes() == original
    assert not launcher.with_suffix(".bat.qwenpaw-maintenance").exists()


def test_restore_preserves_empty_launcher_replacing_maintenance_stub(
    installer,
):
    root, launcher, _, _, run = installer
    launcher.touch()
    backup = launcher.with_suffix(".bat.qwenpaw-maintenance")
    backup.write_text(f'"{root}\\python.exe" host.py', encoding="utf-8-sig")

    result = run(action="Restore")

    assert result.returncode == 0, result.stdout + result.stderr
    assert launcher.read_bytes() == b""
    assert not backup.exists()


@pytest.mark.parametrize("writable_log", [True, False])
def test_query_failure_reports_stage_without_log_dependency(
    installer,
    writable_log,
):
    root, _, log, _, run = installer

    result = run(
        scenario="query-failure",
        log_path=log if writable_log else root,
    )

    assert result.returncode == 1
    assert "Failed to identify installer processes: CIM query unavailable" in (
        result.stdout
    )
    assert "run.ps1:" in result.stdout
    assert "Close these processes" not in result.stdout
    if writable_log:
        assert "CIM query unavailable" in log.read_text(encoding="utf-16")


def test_remaining_processes_are_logged_without_truncation(installer):
    root, _, log, _, run = installer
    processes = [
        process_record(root, f"tools/session-{pid}/python.exe", pid)
        for pid in range(100, 140)
    ]

    result = run(processes=processes)

    assert result.returncode == 1
    saved = log.read_text(encoding="utf-16")
    assert len(saved) > 1024
    assert "Close these processes before continuing:" in saved
    for pid in range(100, 140):
        assert f"PID {pid}" in saved


def test_only_automatic_install_processes_are_stopped(installer):
    root, _, _, stopped, run = installer
    processes = [
        process_record(root, "qwenpaw-desktop.exe", 101),
        process_record(root, "uninstall.exe", 42),
        process_record(root, "uninstall-parent.exe", 41),
        process_record(root.parent / "other", "qwenpaw-desktop.exe", 102),
    ]

    result = run(processes=processes)

    assert result.returncode == 0, result.stdout + result.stderr
    assert stopped.read_text().splitlines() == ["101"]


def test_stop_failure_keeps_blocking_and_records_reason(installer):
    root, _, log, _, run = installer

    result = run(
        processes=[process_record(root, "qwenpaw-desktop.exe", 101)],
        scenario="stop-failure",
    )

    assert result.returncode == 1
    saved = log.read_text(encoding="utf-16")
    assert "Could not stop PID 101: Access denied stopping process" in saved
    assert "Close these processes before continuing:" in saved
