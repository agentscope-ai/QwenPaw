# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from hashlib import sha256
import io
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Iterator

import pytest

from services.runtime_files import runtime_dependencies as dependencies


@pytest.fixture(autouse=True)
def clear_binary_environment() -> Iterator[None]:
    names = (
        dependencies.CREATOR_BINARY_DIR_ENV,
        dependencies.CREATOR_JQ_PATH_ENV,
        dependencies.CREATOR_FFMPEG_PATH_ENV,
        dependencies.CREATOR_FFPROBE_PATH_ENV,
        dependencies.CREATOR_AUTO_INSTALL_BINARIES_ENV,
        dependencies.CREATOR_JQ_BASE_URL_ENV,
    )
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name in names:
            os.environ.pop(name, None)
            if previous[name] is not None:
                os.environ[name] = previous[name]


def _executable(path: Path, content: bytes = b"tool") -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


def _pin_linux_jq(
    monkeypatch: pytest.MonkeyPatch,
    checksum: str,
    payload: bytes,
) -> None:
    key = ("linux", "amd64")
    monkeypatch.setattr(dependencies, "_platform_key", lambda: key)
    asset = ("jq-linux-amd64", checksum)
    monkeypatch.setitem(dependencies._JQ_ASSETS, key, asset)
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)
    body = io.BytesIO(payload)
    monkeypatch.setattr(dependencies, "urlopen", lambda *_a, **_k: body)
    monkeypatch.setenv(dependencies.CREATOR_AUTO_INSTALL_BINARIES_ENV, "1")


def test_ffmpeg_resolves_from_imageio_when_system_path_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)

    path = dependencies.resolve_ffmpeg()

    assert path is not None
    assert "imageio_ffmpeg" in path


def test_system_jq_remains_usable_on_an_unsupported_auto_install_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_jq = _executable(tmp_path / "system-jq")
    monkeypatch.setattr(
        dependencies.shutil,
        "which",
        lambda name: os.fspath(system_jq) if name == "jq" else None,
    )
    key = ("freebsd", "riscv64")
    monkeypatch.setattr(dependencies, "_platform_key", lambda: key)

    status = dependencies.CreatorBinaryManager(
        binary_dir=tmp_path / "bin",
    ).ensure_jq()

    assert status.status == "ok"
    assert status.source == "system"


def test_manager_downloads_and_verifies_pinned_jq(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified-jq-binary"
    _pin_linux_jq(monkeypatch, sha256(payload).hexdigest(), payload)

    manager = dependencies.CreatorBinaryManager(binary_dir=tmp_path / "bin")
    status = manager.ensure_jq()

    assert status.status == "ok"
    assert status.source == f"managed-{dependencies.JQ_VERSION}"
    assert manager.jq_path.read_bytes() == payload
    assert os.access(manager.jq_path, os.X_OK)
    assert os.environ[dependencies.CREATOR_JQ_PATH_ENV] == os.fspath(
        manager.jq_path,
    )


def test_manager_degrades_on_a_jq_checksum_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_linux_jq(monkeypatch, "0" * 64, b"tampered")
    manager = dependencies.CreatorBinaryManager(binary_dir=tmp_path / "bin")

    status = manager.ensure_jq()

    assert status.status == "missing"
    assert status.source == "auto-install-failed"
    assert "SHA-256 verification" in (status.detail or "")
    assert not manager.jq_path.exists()
    assert not list(manager.binary_dir.glob(".jq-download-*"))


def test_ensure_all_opt_in_guard_ffprobe_fallback_and_explicit_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ffmpeg = _executable(tmp_path / "ffmpeg")
    monkeypatch.setenv(dependencies.CREATOR_FFMPEG_PATH_ENV, os.fspath(ffmpeg))
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        dependencies,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "default dependency preparation must not access the network",
        ),
    )

    status = dependencies.CreatorBinaryManager(
        binary_dir=tmp_path / "bin",
    ).ensure_all()

    assert status["jq"].status == "missing"
    assert status["jq"].source == "auto-install-disabled"
    assert status["jq"].required is True
    assert status["ffmpeg"].status == "ok"
    assert status["ffprobe"].status == "fallback"
    assert status["ffprobe"].source == "ffmpeg-metadata"
    monkeypatch.setattr(dependencies, "_LAST_STATUS", status)
    health = dependencies.creator_runtime_dependency_health()
    assert health["status"] == "degraded"
    assert health["tools"]["jq"]["status"] == "missing"

    # Explicit CREATOR_* paths win without any network or auto-install.
    jq = _executable(tmp_path / "jq")
    monkeypatch.setenv(dependencies.CREATOR_JQ_PATH_ENV, os.fspath(jq))
    status = dependencies.CreatorBinaryManager(
        binary_dir=tmp_path / "bin",
    ).ensure_all()
    assert status["jq"].status == "ok"
    assert dependencies.resolve_jq() == os.fspath(jq)


def test_dev_app_imports_in_a_cold_interpreter(tmp_path: Path) -> None:
    """A fresh process must not depend on a lucky prior import order."""

    environment = {
        **os.environ,
        "CREATOR_DATA_ROOT": str(tmp_path / "creator-data"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import dev_main; assert dev_main.app.title"
            " == 'QwenPaw-Creator Local Dev Backend'",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
