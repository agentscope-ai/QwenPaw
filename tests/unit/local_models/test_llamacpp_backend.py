# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from copaw.local_models import llamacpp as downloader_module
from copaw.local_models.llamacpp import LlamaCppBackend


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._buffer = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, chunk_size: int) -> bytes:
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


@pytest.mark.asyncio
async def test_download_extracts_zip_into_dest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "zip-install"

    monkeypatch.setattr(
        "copaw.local_models.llamacpp_downloader.urllib.request.urlopen",
        lambda request, timeout=30: _FakeResponse(_make_zip_payload()),
    )
    monkeypatch.setattr(
        downloader,
        "get_download_url",
        lambda: (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    result = await downloader.download(dest)

    assert result == dest
    assert dest.is_dir()
    assert (dest / "bin" / "server.exe").read_text() == "zip-binary"
    assert not list(dest.glob("*.zip"))
    assert not list(dest.glob("*.part"))


@pytest.mark.asyncio
async def test_download_creates_dest_and_extracts_tar_gz(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "tar-install"

    monkeypatch.setattr(
        "copaw.local_models.llamacpp_downloader.urllib.request.urlopen",
        lambda request, timeout=30: _FakeResponse(_make_tar_gz_payload()),
    )
    monkeypatch.setattr(
        downloader,
        "get_download_url",
        lambda: (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-ubuntu-x64.tar.gz"
        ),
    )

    result = await downloader.download(dest)

    assert result == dest
    assert dest.is_dir()
    assert (dest / "bin" / "server").read_text() == "tar-binary"
    assert not list(dest.glob("*.tar.gz"))
    assert not list(dest.glob("*.part"))


@pytest.mark.asyncio
async def test_download_rejects_existing_file_dest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest_file = tmp_path / "not-a-directory"
    dest_file.write_text("content")

    with pytest.raises(ValueError, match="dest must be a directory path"):
        await downloader.download(dest_file)


@pytest.mark.asyncio
async def test_download_can_run_as_asyncio_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "task-install"

    monkeypatch.setattr(
        "copaw.local_models.llamacpp_downloader.urllib.request.urlopen",
        lambda request, timeout=30: _FakeResponse(_make_zip_payload()),
    )
    monkeypatch.setattr(
        downloader,
        "get_download_url",
        lambda: (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    task = asyncio.create_task(downloader.download(dest))
    result = await task

    assert result == dest
    assert (dest / "bin" / "server.exe").read_text() == "zip-binary"


@pytest.mark.asyncio
async def test_download_flattens_single_top_level_archive_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "flattened-install"

    monkeypatch.setattr(
        "copaw.local_models.llamacpp_downloader.urllib.request.urlopen",
        lambda request, timeout=30: _FakeResponse(
            _make_tar_gz_payload_with_top_level_dir(),
        ),
    )
    monkeypatch.setattr(
        downloader,
        "get_download_url",
        lambda: (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-ubuntu-x64.tar.gz"
        ),
    )

    result = await downloader.download(dest)

    assert result == dest
    assert (dest / "bin" / "server").read_text() == "tar-binary"
    assert not (dest / "llama-b1234").exists()
