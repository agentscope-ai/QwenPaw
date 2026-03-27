# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import io
import tarfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import copaw.local_models.llamacpp as downloader_module
from copaw.local_models.llamacpp import LlamaCppBackend


class _FakeServerProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        chunk_delay: float = 0.0,
    ) -> None:
        self._buffer = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}
        self._chunk_delay = chunk_delay

    def read(self, chunk_size: int) -> bytes:
        if self._chunk_delay:
            time.sleep(self._chunk_delay)
        return self._buffer.read(chunk_size)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _make_zip_payload() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bin/server.exe", "zip-binary")
    return buffer.getvalue()


def _make_tar_gz_payload() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        content = b"tar-binary"
        info = tarfile.TarInfo(name="bin/server")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _make_tar_gz_payload_with_top_level_dir() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        content = b"tar-binary"
        info = tarfile.TarInfo(name="llama-b1234/bin/server")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _build_downloader(
    monkeypatch: pytest.MonkeyPatch,
) -> LlamaCppBackend:
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_os_name",
        lambda: "linux",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_architecture",
        lambda: "x64",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_cuda_version",
        lambda: None,
    )
    return LlamaCppBackend(
        base_url="https://example.com/releases",
        release_tag="b1234",
    )


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    *,
    chunk_delay: float = 0.0,
) -> None:
    monkeypatch.setattr(
        downloader_module.urllib.request,
        "urlopen",
        lambda request, timeout=30: _FakeResponse(
            payload,
            chunk_delay=chunk_delay,
        ),
    )


def _patch_download_url(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setattr(
        LlamaCppBackend,
        "download_url",
        property(lambda self: url),
    )


async def _wait_for_status(
    downloader: LlamaCppBackend,
    *statuses: str,
    timeout: float = 3.0,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        progress = downloader.get_download_progress()
        if progress["status"] in statuses:
            return progress
        await asyncio.sleep(0.05)
    raise AssertionError(
        "Timed out waiting for statuses "
        f"{statuses}, got {downloader.get_download_progress()}",
    )


def test_get_download_progress_returns_idle_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)

    assert downloader.get_download_progress() == {
        "status": "idle",
        "model_name": None,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed_bytes_per_sec": 0.0,
        "source": None,
        "error": None,
        "local_path": None,
    }


@pytest.mark.asyncio
async def test_download_supports_progress_polling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "tar-install"
    downloader.target_dir = dest
    url = (
        "https://example.com/releases/b1234/"
        "llama-b1234-bin-ubuntu-x64.tar.gz"
    )

    _patch_urlopen(monkeypatch, _make_tar_gz_payload())
    _patch_download_url(monkeypatch, url)

    downloader.download()
    progress = await _wait_for_status(downloader, "completed")

    assert dest.is_dir()
    assert (dest / "bin" / "server").read_text() == "tar-binary"
    assert progress["status"] == "completed"
    assert progress["source"] == url
    assert progress["local_path"] == str(dest)
    assert progress["downloaded_bytes"] == progress["total_bytes"]
    assert not list(dest.glob("*.tar.gz"))
    assert not list(dest.glob("*.part"))


@pytest.mark.asyncio
async def test_download_extracts_zip_into_dest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "zip-install"
    downloader.target_dir = dest

    _patch_urlopen(monkeypatch, _make_zip_payload())
    _patch_download_url(
        monkeypatch,
        (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    downloader.download()
    progress = await _wait_for_status(downloader, "completed")

    assert dest.is_dir()
    assert (dest / "bin" / "server.exe").read_text() == "zip-binary"
    assert progress["status"] == "completed"
    assert not list(dest.glob("*.zip"))
    assert not list(dest.glob("*.part"))


@pytest.mark.asyncio
async def test_download_rejects_existing_file_dest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest_file = tmp_path / "not-a-directory"
    dest_file.write_text("content")
    downloader.target_dir = dest_file

    with pytest.raises(ValueError, match="dest must be a directory path"):
        downloader.download()


@pytest.mark.asyncio
async def test_cancel_download_updates_status_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "cancel-install"
    downloader.target_dir = dest

    _patch_urlopen(
        monkeypatch,
        _make_zip_payload() * 32,
        chunk_delay=0.02,
    )
    _patch_download_url(
        monkeypatch,
        (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    downloader.download(chunk_size=64)

    await _wait_for_status(downloader, "downloading")
    deadline = asyncio.get_running_loop().time() + 3.0
    while asyncio.get_running_loop().time() < deadline:
        if downloader.get_download_progress()["downloaded_bytes"] > 0:
            break
        await asyncio.sleep(0.02)

    downloader.cancel_download()
    progress = await _wait_for_status(downloader, "cancelled")

    assert progress["status"] == "cancelled"
    assert progress["speed_bytes_per_sec"] == 0.0
    assert progress["local_path"] is None
    assert not list(dest.glob("*.part"))


@pytest.mark.asyncio
async def test_download_starts_background_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "task-install"
    downloader.target_dir = dest

    _patch_urlopen(monkeypatch, _make_zip_payload())
    _patch_download_url(
        monkeypatch,
        (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    downloader.download()
    progress = await _wait_for_status(downloader, "completed")

    assert progress["status"] == "completed"
    assert (dest / "bin" / "server.exe").read_text() == "zip-binary"


@pytest.mark.asyncio
async def test_download_flattens_single_top_level_archive_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "flattened-install"
    downloader.target_dir = dest

    _patch_urlopen(
        monkeypatch,
        _make_tar_gz_payload_with_top_level_dir(),
    )
    _patch_download_url(
        monkeypatch,
        (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-ubuntu-x64.tar.gz"
        ),
    )

    downloader.download()
    progress = await _wait_for_status(downloader, "completed")

    assert progress["local_path"] == str(dest)
    assert (dest / "bin" / "server").read_text() == "tar-binary"
    assert not (dest / "llama-b1234").exists()


def test_force_shutdown_server_kills_process_group_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    process = _FakeServerProcess()
    killed: list[tuple[int, int]] = []

    downloader._server_process = process
    downloader._server_port = 8080
    downloader._server_model_name = "demo"
    downloader._server_owns_process_group = True
    downloader._server_log_task = SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(downloader_module.os, "name", "posix")
    monkeypatch.setattr(downloader_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        downloader_module.os,
        "killpg",
        lambda pgid, sig: killed.append((pgid, int(sig))),
    )
    monkeypatch.setattr(
        downloader,
        "_wait_for_process_exit",
        lambda pid, timeout: True,
    )

    downloader.force_shutdown_server()

    assert killed == [(process.pid, int(downloader_module.signal.SIGTERM))]
    assert downloader.get_server_status() == {
        "running": False,
        "port": None,
        "model_name": None,
        "pid": None,
    }


def test_force_shutdown_server_escalates_to_kill_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    process = _FakeServerProcess()
    signals: list[int] = []

    downloader._server_process = process
    downloader._server_owns_process_group = False
    downloader._server_log_task = SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(
        downloader,
        "_wait_for_process_exit",
        lambda pid, timeout: timeout < 2.0,
    )
    monkeypatch.setattr(process, "terminate", lambda: signals.append(15))
    monkeypatch.setattr(process, "kill", lambda: signals.append(9))

    downloader.force_shutdown_server()

    assert signals == [15, 9]
