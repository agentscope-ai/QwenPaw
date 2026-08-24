# -*- coding: utf-8 -*-
"""Windows NSIS process-cleanup integration tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows NSIS only"),
]

SCRIPT = Path("console/src-tauri/nsis/manage-install-processes.ps1").resolve()


def _recognized_install(root: Path) -> None:
    (root / "qwenpaw-desktop.exe").touch()
    backend = root / "binaries" / "qwenpaw-backend"
    backend.mkdir(parents=True)
    (backend / "qwenpaw-backend.exe").touch()


def _copy_cmd(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy2(Path(os.environ["COMSPEC"]), destination))


def _start_cmd(executable: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # pylint: disable=consider-using-with
        [str(executable), "/d", "/c", "pause"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run_helper(
    root: Path,
    home: Path,
    state: Path,
    *extra: str,
    constrained: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["USERPROFILE"] = str(home)
    if constrained:
        assert not extra
        env["QWENPAW_TEST_SCRIPT"] = str(SCRIPT)
        env["QWENPAW_TEST_ROOT"] = str(root)
        env["QWENPAW_TEST_STATE"] = str(state)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            '$ExecutionContext.SessionState.LanguageMode = '
            '"ConstrainedLanguage"; '
            "& $env:QWENPAW_TEST_SCRIPT -InstallDir $env:QWENPAW_TEST_ROOT "
            "-StateFile $env:QWENPAW_TEST_STATE; exit $LASTEXITCODE",
        ]
    else:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-InstallDir",
            str(root),
            "-StateFile",
            str(state),
            *extra,
        ]
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def test_fresh_and_unrelated_targets_do_not_trigger_cleanup(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state.json"
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    assert _run_helper(fresh, home, state).returncode == 0

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "other-app.exe").touch()
    assert _run_helper(unrelated, home, state).returncode == 3

    recognized = tmp_path / "recognized"
    recognized.mkdir()
    _recognized_install(recognized)
    launcher = home / ".qwenpaw" / "bin" / "qwenpaw-nm-host.bat"
    backup = launcher.with_name(f"{launcher.name}.qwenpaw-maintenance")
    backup.parent.mkdir(parents=True)
    original = f'@echo off\n"{recognized}\\python.exe" %*\n'
    backup.write_text(original, encoding="utf-8")
    ignored = _run_helper(unrelated, home, state, "-Action", "Restore")
    assert ignored.returncode == 0
    assert backup.exists()
    assert not launcher.exists()

    assert _run_helper(recognized, home, state).returncode == 0
    assert backup.exists()
    assert not launcher.exists()
    restored = _run_helper(recognized, home, state, "-Action", "Restore")
    assert restored.returncode == 0
    assert launcher.read_text(encoding="utf-8") == original


def test_prepare_gates_launcher_and_stops_only_consented_processes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "QwenPaw Desktop"
    root.mkdir()
    _recognized_install(root)
    known_exe = _copy_cmd(
        root / "binaries" / "python-runtime" / "python" / "python.exe",
    )
    helper_exe = _copy_cmd(root / "qwenpaw-computer-use-helper.exe")
    unknown_exe = _copy_cmd(root / "third-party-helper.exe")

    home = tmp_path / "home"
    launcher = home / ".qwenpaw" / "bin" / "qwenpaw-nm-host.bat"
    launcher.parent.mkdir(parents=True)
    original_launcher = f'@echo off\n"{known_exe}" "nm_host.py" %*\n'
    launcher.write_text(original_launcher, encoding="utf-8")
    state = tmp_path / "state.json"

    known = _start_cmd(known_exe)
    helper = _start_cmd(helper_exe)
    unknown = _start_cmd(unknown_exe)
    outside = _start_cmd(Path(os.environ["COMSPEC"]))
    try:
        first = _run_helper(root, home, state, constrained=True)
        assert first.returncode == 2
        assert "third-party-helper.exe" in first.stdout
        known.wait(timeout=5)
        helper.wait(timeout=5)
        assert unknown.poll() is None
        assert outside.poll() is None
        assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text(
            encoding="ascii",
        )

        confirmed = _run_helper(
            root,
            home,
            state,
            "-TerminateUnknown",
        )
        assert confirmed.returncode == 0
        unknown.wait(timeout=5)
        assert outside.poll() is None

        restored = _run_helper(root, home, state, "-Action", "Restore")
        assert restored.returncode == 0
        assert launcher.read_text(encoding="utf-8") == original_launcher
    finally:
        for process in (known, helper, unknown, outside):
            _stop(process)
        _run_helper(root, home, state, "-Action", "Restore")


def test_confirmed_process_identity_is_revalidated(tmp_path: Path) -> None:
    root = tmp_path / "QwenPaw Desktop"
    root.mkdir()
    _recognized_install(root)
    unknown_exe = _copy_cmd(root / "third-party-helper.exe")
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state.json"
    unknown = _start_cmd(unknown_exe)
    try:
        assert _run_helper(root, home, state).returncode == 2
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        saved["Processes"][0]["CreationDate"] = "stale identity"
        state.write_text(json.dumps(saved), encoding="utf-8")

        stale = _run_helper(
            root,
            home,
            state,
            "-TerminateUnknown",
        )
        assert stale.returncode == 2
        assert unknown.poll() is None

        assert (
            _run_helper(
                root,
                home,
                state,
                "-TerminateUnknown",
            ).returncode
            == 0
        )
        unknown.wait(timeout=5)
    finally:
        _stop(unknown)
        _run_helper(root, home, state, "-Action", "Restore")
