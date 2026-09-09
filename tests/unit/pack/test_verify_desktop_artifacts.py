"""Regression tests for downloaded desktop updater integrity checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPOSITORY_ROOT / "scripts" / "pack" / "verify_desktop_artifacts.py"


def _write_checksum(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(f"{path}.sha256").write_text(
        f"{digest}  {path.name}\n",
        encoding="ascii",
    )


def _write_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _write_checksum(path)
    return path


def _write_metadata(
    path: Path,
    *,
    target: str,
    artifact: str,
    signature: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "target": target,
                "artifact": artifact,
                "signature": signature,
            },
        ),
        encoding="utf-8",
    )
    _write_checksum(path)
    return path


def _create_valid_artifacts(root: Path) -> dict[str, Path]:
    windows_name = "QwenPaw-Tauri-1.0.0-Windows-setup.exe"
    windows = _write_file(
        root / "QwenPaw-Desktop-Tauri-Windows-1.0.0" / windows_name,
        b"windows installer",
    )

    macos = root / ("QwenPaw-Desktop-Tauri-macOS-1.0.0/QwenPaw-Tauri-1.0.0-macOS.zip")
    macos.parent.mkdir(parents=True)
    with zipfile.ZipFile(macos, "w") as archive:
        archive.writestr("QwenPaw.app/Contents/MacOS/QwenPaw", b"app")
    _write_checksum(macos)

    windows_updater = root / "tauri-updater-meta-windows"
    windows_signature = _write_file(
        windows_updater / f"{windows_name}.sig",
        b"complete windows signature",
    )
    windows_metadata = _write_metadata(
        windows_updater / "tauri-windows-x86_64-updater.json",
        target="windows-x86_64",
        artifact=windows.name,
        signature=windows_signature.name,
    )

    macos_updater = root / "tauri-updater-meta-macos"
    macos_archive = _write_file(
        macos_updater / "QwenPaw-Tauri-1.0.0-macOS.app.tar.gz",
        b"macOS updater archive",
    )
    macos_signature = _write_file(
        Path(f"{macos_archive}.sig"),
        b"complete macOS signature",
    )
    macos_metadata = _write_metadata(
        macos_updater / "tauri-darwin-aarch64-updater.json",
        target="darwin-aarch64",
        artifact=macos_archive.name,
        signature=macos_signature.name,
    )

    return {
        "windows_signature": windows_signature,
        "windows_metadata": windows_metadata,
        "macos_signature": macos_signature,
        "macos_metadata": macos_metadata,
    }


def _run_verifier(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--root",
            str(root),
            "--require",
            "windows",
            "--require",
            "macos",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_valid_installers_and_updater_metadata_pass(tmp_path: Path) -> None:
    _create_valid_artifacts(tmp_path)

    result = _run_verifier(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "verified windows-updater metadata" in result.stdout
    assert "verified macos-updater metadata" in result.stdout


@pytest.mark.parametrize(
    "key",
    [
        "windows_signature",
        "windows_metadata",
        "macos_signature",
        "macos_metadata",
    ],
)
def test_tampered_updater_sidecar_fails_checksum(
    tmp_path: Path,
    key: str,
) -> None:
    files = _create_valid_artifacts(tmp_path)
    files[key].write_bytes(b"x")

    result = _run_verifier(tmp_path)

    assert result.returncode == 1
    assert "SHA-256 mismatch" in result.stderr
