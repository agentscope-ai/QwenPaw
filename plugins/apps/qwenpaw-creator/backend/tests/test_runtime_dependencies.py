# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from hashlib import sha256
import io
import os
from pathlib import Path
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
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def _executable(path: Path, content: bytes = b"tool") -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


def test_resolvers_prefer_explicit_creator_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jq = _executable(tmp_path / "jq")
    ffmpeg = _executable(tmp_path / "ffmpeg")
    ffprobe = _executable(tmp_path / "ffprobe")
    monkeypatch.setenv(dependencies.CREATOR_JQ_PATH_ENV, os.fspath(jq))
    monkeypatch.setenv(dependencies.CREATOR_FFMPEG_PATH_ENV, os.fspath(ffmpeg))
    monkeypatch.setenv(
        dependencies.CREATOR_FFPROBE_PATH_ENV,
        os.fspath(ffprobe),
    )

    assert dependencies.resolve_jq() == os.fspath(jq)
    assert dependencies.resolve_ffmpeg() == os.fspath(ffmpeg)
    assert dependencies.resolve_ffprobe() == os.fspath(ffprobe)


def test_ffmpeg_resolves_from_imageio_when_system_path_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)

    path = dependencies.resolve_ffmpeg()

    assert path is not None
    assert Path(path).is_file()
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
    monkeypatch.setattr(
        dependencies,
        "_platform_key",
        lambda: ("freebsd", "riscv64"),
    )

    status = dependencies.CreatorBinaryManager(
        binary_dir=tmp_path / "bin",
    ).ensure_jq()

    assert status.status == "ok"
    assert status.source == "system"
    assert status.path == os.fspath(system_jq)


def test_manager_downloads_and_verifies_pinned_jq(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified-jq-binary"
    checksum = sha256(payload).hexdigest()
    monkeypatch.setattr(
        dependencies,
        "_platform_key",
        lambda: ("linux", "amd64"),
    )
    monkeypatch.setitem(
        dependencies._JQ_ASSETS,
        ("linux", "amd64"),
        ("jq-linux-amd64", checksum),
    )
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        dependencies,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(payload),
    )
    monkeypatch.setenv(
        dependencies.CREATOR_JQ_BASE_URL_ENV,
        "https://mirror.invalid/jq",
    )
    monkeypatch.setenv(dependencies.CREATOR_AUTO_INSTALL_BINARIES_ENV, "1")

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
    monkeypatch.setattr(
        dependencies,
        "_platform_key",
        lambda: ("linux", "amd64"),
    )
    monkeypatch.setitem(
        dependencies._JQ_ASSETS,
        ("linux", "amd64"),
        ("jq-linux-amd64", "0" * 64),
    )
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        dependencies,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b"tampered"),
    )
    monkeypatch.setenv(dependencies.CREATOR_AUTO_INSTALL_BINARIES_ENV, "1")
    manager = dependencies.CreatorBinaryManager(binary_dir=tmp_path / "bin")

    status = manager.ensure_jq()

    assert status.status == "missing"
    assert status.source == "auto-install-failed"
    assert "SHA-256 verification" in (status.detail or "")
    assert not manager.jq_path.exists()
    assert not list(manager.binary_dir.glob(".jq-download-*"))


def test_jq_auto_install_is_opt_in_and_missing_jq_is_degraded(
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

    monkeypatch.setattr(dependencies, "_LAST_STATUS", status)
    health = dependencies.creator_runtime_dependency_health()
    assert health["status"] == "degraded"
    assert health["tools"]["jq"]["status"] == "missing"


def test_ffprobe_is_optional_when_managed_ffmpeg_is_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jq = _executable(tmp_path / "jq")
    ffmpeg = _executable(tmp_path / "ffmpeg")
    monkeypatch.setenv(dependencies.CREATOR_JQ_PATH_ENV, os.fspath(jq))
    monkeypatch.setenv(dependencies.CREATOR_FFMPEG_PATH_ENV, os.fspath(ffmpeg))
    monkeypatch.setattr(dependencies.shutil, "which", lambda _name: None)

    status = dependencies.CreatorBinaryManager(
        binary_dir=tmp_path / "bin",
    ).ensure_all()

    assert status["jq"].status == "ok"
    assert status["ffmpeg"].status == "ok"
    assert status["ffprobe"].status == "fallback"
    assert status["ffprobe"].source == "ffmpeg-metadata"
