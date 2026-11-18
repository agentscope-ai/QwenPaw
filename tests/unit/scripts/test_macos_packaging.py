# -*- coding: utf-8 -*-
"""Execute macOS packaging scripts with controlled platform commands."""

import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="requires POSIX Bash",
)


def _command(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run(tmp_path, script, *args):
    return subprocess.run(
        ["bash", str(ROOT / script), *map(str, args)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path / "home"),
            "GITHUB_ENV": str(tmp_path / "github-env"),
            "COMMAND_LOG": str(tmp_path / "commands.log"),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("app", [True, False], ids=["app", "backend"])
def test_signing_skips_debug_symbols_and_keeps_native_signatures(
    tmp_path,
    app,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _command(bin_dir, "uname", "echo Darwin\n")
    _command(bin_dir, "file", "echo 'Mach-O 64-bit bundle arm64'\n")
    _command(bin_dir, "codesign", 'printf "%s\\n" "$*" >> "$COMMAND_LOG"\n')
    target = tmp_path / ("Desktop.app" if app else "backend")
    native = target / "native.so"
    debug = target / "native.so.dSYM/Contents/Resources/DWARF/native.so"
    framework = target / "Python.framework"
    for path in (native, debug, framework / "Python"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    result = _run(tmp_path, "scripts/pack-tauri/sign_macos_bundle.sh", target)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "commands.log").read_text().splitlines()
    assert all(".dSYM" not in call for call in calls)
    assert f"--force --sign - --timestamp=none {native}" in calls
    assert f"--force --sign - --timestamp=none {framework}" in calls
    assert not any(call.endswith(str(framework / "Python")) for call in calls)
    if app:
        assert calls[-2:] == [
            f"--force --sign - --timestamp=none {target}",
            f"--verify --deep --strict --verbose=2 {target}",
        ]
    else:
        assert f"--verify --verbose=2 {native}" in calls
        assert f"--verify --verbose=2 {framework}" in calls


@pytest.mark.parametrize("missing", [None, "app", "executable"])
def test_launcher_uses_real_top_level_app(tmp_path, missing):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _command(bin_dir, "open", 'printf "%s\\n" "$1" >> "$COMMAND_LOG"\n')
    for name in ("xattr", "sleep", "ps", "curl"):
        _command(bin_dir, name, "exit 0\n")
    app = "QwenPaw Desktop.app"
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(
        dist / "QwenPaw-Tauri-test-macOS.zip",
        "w",
    ) as archive:
        archive.writestr(f"__MACOSX/{app}/._Contents", b"metadata")
        if missing != "app":
            archive.writestr(f"{app}/Contents/Info.plist", b"plist")
            if missing != "executable":
                executable = zipfile.ZipInfo(
                    f"{app}/Contents/MacOS/qwenpaw-desktop",
                )
                executable.external_attr = 0o100755 << 16
                archive.writestr(executable, b"binary")
    port = tmp_path / "home/.qwenpaw/desktop_port"
    port.parent.mkdir(parents=True)
    port.write_text("12345")

    result = _run(tmp_path, "scripts/verify/launch_tauri_macos.sh")

    log = tmp_path / "commands.log"
    if missing:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not log.exists(), "invalid bundle must not be launched"
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert log.read_text().splitlines() == [f"dist/verify-tauri/{app}"]
        assert (tmp_path / "github-env").read_text() == (
            "BASE_URL=http://127.0.0.1:12345\n"
        )
