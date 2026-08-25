# -*- coding: utf-8 -*-
"""Windows NSIS process-cleanup integration tests."""

from __future__ import annotations

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


def _start_cmd(
    executable: Path,
    marker: str | None = None,
) -> subprocess.Popen[bytes]:
    command = "pause" if marker is None else f"title {marker} & pause"
    return subprocess.Popen(  # pylint: disable=consider-using-with
        [str(executable), "/d", "/c", command],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run_helper(
    root: Path,
    home: Path,
    *extra: str,
    constrained: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["USERPROFILE"] = str(home)
    if constrained:
        assert not extra
        env["QWENPAW_TEST_SCRIPT"] = str(SCRIPT)
        env["QWENPAW_TEST_ROOT"] = str(root)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "$ExecutionContext.SessionState.LanguageMode = "
            '"ConstrainedLanguage"; '
            "& $env:QWENPAW_TEST_SCRIPT "
            "-InstallDir $env:QWENPAW_TEST_ROOT; exit $LASTEXITCODE",
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


def test_unrecognized_targets_do_not_trigger_cleanup(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    assert _run_helper(fresh, home).returncode == 0

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    native_host_exe = _copy_cmd(
        unrelated / "binaries" / "python-runtime" / "python" / "python.exe",
    )
    native_host = _start_cmd(native_host_exe, "qwenpaw-nm-host.py")
    try:
        assert _run_helper(unrelated, home).returncode == 0
        assert native_host.poll() is None
    finally:
        _stop(native_host)


def test_prepare_stops_only_automatic_processes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "QwenPaw Desktop"
    root.mkdir()
    _recognized_install(root)
    backend_exe = _copy_cmd(
        root / "binaries" / "qwenpaw-backend" / "qwenpaw-backend.exe",
    )
    native_host_exe = _copy_cmd(
        root / "binaries" / "python-runtime" / "python" / "python.exe",
    )
    helper_exe = _copy_cmd(root / "qwenpaw-computer-use-helper.exe")
    node_exe = _copy_cmd(root / "binaries" / "node-runtime" / "node.exe")
    unknown_exe = _copy_cmd(root / "third-party-helper.exe")
    other_root = tmp_path / "Other QwenPaw"
    other_backend_exe = _copy_cmd(
        other_root / "binaries" / "qwenpaw-backend" / "qwenpaw-backend.exe",
    )

    home = tmp_path / "home"
    launcher = home / ".qwenpaw" / "bin" / "qwenpaw-nm-host.bat"
    launcher.parent.mkdir(parents=True)
    original_launcher = (
        f'@echo off\n"{native_host_exe}" "qwenpaw-nm-host.py" %*\n'
    )
    launcher.write_text(original_launcher, encoding="utf-8")

    backend = _start_cmd(backend_exe)
    native_host = _start_cmd(native_host_exe, "qwenpaw-nm-host.py")
    helper = _start_cmd(helper_exe)
    node = _start_cmd(node_exe)
    unknown = _start_cmd(unknown_exe)
    other_backend = _start_cmd(other_backend_exe)
    try:
        first = _run_helper(root, home, constrained=True)
        assert first.returncode == 1
        assert "qwenpaw-computer-use-helper.exe" in first.stdout
        assert "node.exe" in first.stdout
        assert "third-party-helper.exe" in first.stdout
        backend.wait(timeout=5)
        native_host.wait(timeout=5)
        assert helper.poll() is None
        assert node.poll() is None
        assert unknown.poll() is None
        assert other_backend.poll() is None
        assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text(
            encoding="ascii",
        )

        for process in (helper, node, unknown):
            _stop(process)
        assert _run_helper(root, home).returncode == 0
        assert other_backend.poll() is None

        restored = _run_helper(root, home, "-Action", "Restore")
        assert restored.returncode == 0
        assert launcher.read_text(encoding="utf-8") == original_launcher
    finally:
        for process in (
            backend,
            native_host,
            helper,
            node,
            unknown,
            other_backend,
        ):
            _stop(process)
        _run_helper(root, home, "-Action", "Restore")


def test_restore_is_scoped_to_requested_install(tmp_path: Path) -> None:
    root = tmp_path / "QwenPaw Desktop"
    root.mkdir()
    _recognized_install(root)
    other_root = tmp_path / "Other QwenPaw"
    other_root.mkdir()
    _recognized_install(other_root)

    home = tmp_path / "home"
    launcher = home / ".qwenpaw" / "bin" / "qwenpaw-nm-host.bat"
    launcher.parent.mkdir(parents=True)
    original = f'@echo off\n"{root}\\python.exe" %*\n'
    launcher.write_text(original, encoding="utf-8")
    backup = launcher.with_name(f"{launcher.name}.qwenpaw-maintenance")

    assert _run_helper(root, home).returncode == 0
    assert backup.exists()

    assert _run_helper(other_root, home, "-Action", "Restore").returncode == 0
    assert backup.exists()
    assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text(
        encoding="ascii",
    )

    assert _run_helper(root, home, "-Action", "Restore").returncode == 0
    assert launcher.read_text(encoding="utf-8") == original
