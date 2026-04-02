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
from typing import Any, cast

import httpx
import pytest

import copaw.local_models.llamacpp as downloader_module
from copaw.utils.command_runner import (
    CommandExecutionError,
    CommandResult,
    ShutdownResult,
)
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


class _FakeHttpxResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeBlockingStdout:
    def readline(self) -> bytes:
        return b""


class _FakePopen:
    def __init__(self, pid: int = 2468) -> None:
        self.pid = pid
        self.stdout = _FakeBlockingStdout()
        self._returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._returncode

    def wait(self) -> int:
        self._returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = -15

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9


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


class _FakeStreamResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        chunk_delay: float = 0.0,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self._chunk_delay = chunk_delay
        self.status_code = status_code
        self.headers = headers or {"Content-Length": str(len(payload))}
        self.request = httpx.Request("GET", "https://example.com/file")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "download failed",
                request=self.request,
                response=httpx.Response(
                    self.status_code,
                    request=self.request,
                ),
            )

    def iter_bytes(self, chunk_size: int) -> object:
        for index in range(0, len(self._payload), chunk_size):
            if self._chunk_delay:
                time.sleep(self._chunk_delay)
            yield self._payload[index : index + chunk_size]

    def __enter__(self) -> _FakeStreamResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeHttpxClient:
    def __init__(
        self,
        payload: bytes,
        *,
        chunk_delay: float = 0.0,
        status_code: int = 200,
        exc: Exception | None = None,
    ) -> None:
        self._payload = payload
        self._chunk_delay = chunk_delay
        self._status_code = status_code
        self._exc = exc
        self.stream_calls: list[tuple[str, str, dict[str, str] | None]] = []

    def stream(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> _FakeStreamResponse:
        self.stream_calls.append((method, url, headers))
        if self._exc is not None:
            raise self._exc
        return _FakeStreamResponse(
            self._payload,
            chunk_delay=self._chunk_delay,
            status_code=self._status_code,
        )

    def __enter__(self) -> _FakeHttpxClient:
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
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_macos_version",
        lambda: (13, 0),
    )
    return LlamaCppBackend(
        base_url="https://example.com/releases",
        release_tag="b1234",
    )


def test_init_rejects_macos_lower_than_13(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_os_name",
        lambda: "macos",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_architecture",
        lambda: "arm64",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_cuda_version",
        lambda: None,
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_macos_version",
        lambda: (12, 7, 6),
    )

    llamacpp = LlamaCppBackend(
        base_url="https://example.com/releases",
        release_tag="b1234",
    )
    ok, message = llamacpp.check_llamacpp_installability()
    assert not ok
    assert (
        message == "Unsupported macOS version: 12.7.6 (requires 13.3 or later)"
    )


def test_init_allows_macos_13_and_above(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_os_name",
        lambda: "macos",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_architecture",
        lambda: "arm64",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_cuda_version",
        lambda: None,
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_macos_version",
        lambda: (13, 3),
    )

    downloader = LlamaCppBackend(
        base_url="https://example.com/releases",
        release_tag="b1234",
    )

    assert downloader.os_name == "macos"


@pytest.mark.asyncio
async def test_list_devices_returns_trimmed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    calls: list[list[str]] = []

    async def fake_run_command_async(
        command: list[str],
        **_kwargs: Any,
    ) -> CommandResult:
        del _kwargs
        calls.append(command)
        return CommandResult(
            command=command,
            returncode=0,
            stdout="CPU\n\nCUDA0\n",
            stderr="",
        )

    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader_module,
        "run_command_async",
        fake_run_command_async,
    )

    assert await downloader.list_devices() == ["CPU", "CUDA0"]
    assert calls == [[str(downloader.executable), "--list-devices"]]


@pytest.mark.asyncio
async def test_get_version_reads_stderr_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)

    async def fake_run_command_async(
        command: list[str],
        **_kwargs: Any,
    ) -> CommandResult:
        del _kwargs
        return CommandResult(
            command=command,
            returncode=0,
            stdout="",
            stderr="llama-server version 1.2.3\n",
        )

    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader_module,
        "run_command_async",
        fake_run_command_async,
    )

    assert await downloader.get_version() == "llama-server version 1.2.3"


@pytest.mark.asyncio
async def test_get_version_raises_when_command_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)

    async def fake_run_command_async(
        command: list[str],
        **_kwargs: Any,
    ) -> CommandResult:
        del _kwargs
        raise CommandExecutionError(
            command,
            "boom",
            returncode=1,
            stderr="boom",
        )

    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader_module,
        "run_command_async",
        fake_run_command_async,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await downloader.get_version()


@pytest.mark.asyncio
async def test_list_devices_raises_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)

    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (False, "llama.cpp is not installed"),
    )

    with pytest.raises(RuntimeError, match="llama.cpp is not installed"):
        await downloader.list_devices()


@pytest.mark.parametrize(
    ("cuda_version", "expected"),
    [
        ("12.3", None),
        ("12.4", "12.4"),
        ("12.8", "12.4"),
        ("13.0", "13.1"),
    ],
)
def test_init_maps_supported_windows_cuda_versions(
    monkeypatch: pytest.MonkeyPatch,
    cuda_version: str,
    expected: str | None,
) -> None:
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_os_name",
        lambda: "windows",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_architecture",
        lambda: "x64",
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_cuda_version",
        lambda: cuda_version,
    )
    monkeypatch.setattr(
        downloader_module.system_info,
        "get_macos_version",
        lambda: None,
    )

    downloader = LlamaCppBackend(
        base_url="https://example.com/releases",
        release_tag="b1234",
    )

    assert downloader.cuda_version == expected


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    *,
    chunk_delay: float = 0.0,
) -> None:
    monkeypatch.setattr(
        downloader_module.httpx,
        "Client",
        lambda **kwargs: _FakeHttpxClient(
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


def test_download_sync_closes_temp_fd_before_request_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "request-failure-install"
    closed_fds: list[int] = []
    created_temp_path: Path | None = None

    original_mkstemp = downloader_module.tempfile.mkstemp
    original_close = downloader_module.os.close

    def tracked_mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
        nonlocal created_temp_path
        fd, temp_name = original_mkstemp(*args, **kwargs)
        created_temp_path = Path(temp_name)
        return fd, temp_name

    def tracked_close(fd: int) -> None:
        closed_fds.append(fd)
        original_close(fd)

    monkeypatch.setattr(
        downloader_module.tempfile,
        "mkstemp",
        tracked_mkstemp,
    )
    monkeypatch.setattr(downloader_module.os, "close", tracked_close)
    request = httpx.Request("GET", "https://example.com/fail")
    monkeypatch.setattr(
        downloader_module.httpx,
        "Client",
        lambda **kwargs: _FakeHttpxClient(
            b"",
            exc=httpx.ReadError("boom", request=request),
        ),
    )
    _patch_download_url(
        monkeypatch,
        (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    with pytest.raises(httpx.ReadError, match="boom"):
        downloader._download_sync(dest)

    assert created_temp_path is not None
    assert closed_fds
    assert not created_temp_path.exists()


def test_download_sync_uses_browser_like_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "header-install"
    fake_client = _FakeHttpxClient(_make_zip_payload())

    monkeypatch.setattr(
        downloader_module.httpx,
        "Client",
        lambda **kwargs: fake_client,
    )
    _patch_download_url(
        monkeypatch,
        (
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip"
        ),
    )

    downloader._download_sync(dest)

    assert fake_client.stream_calls == [
        (
            "GET",
            "https://example.com/releases/b1234/"
            "llama-b1234-bin-win-cpu-x64.zip",
            downloader._download_headers,
        ),
    ]


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
async def test_download_ignores_stale_part_file_from_previous_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    dest = tmp_path / "stale-part-install"
    downloader.target_dir = dest
    dest.mkdir(parents=True)

    stale_part = dest / "llama-b1234-bin-win-cpu-x64.zip.part"
    stale_part.write_text("stale")

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
    assert stale_part.exists()
    assert stale_part.read_text() == "stale"
    assert not list(dest.glob("*.zip"))


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


@pytest.mark.asyncio
async def test_setup_server_falls_back_on_windows_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    model_path = tmp_path / "demo.gguf"
    model_path.write_text("gguf")
    start_calls: list[tuple[list[str], dict[str, object]]] = []

    class _FakeAsyncStdout:
        async def readline(self) -> bytes:
            return b""

    class _FakeStartedProcess:
        def __init__(self) -> None:
            self.pid = 2468
            self.stdout = _FakeAsyncStdout()
            self.returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    async def fake_start_process_async(command, **kwargs):
        start_calls.append((list(command), kwargs))
        return _FakeStartedProcess()

    async def fake_server_ready(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(downloader_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader_module,
        "start_process_async",
        fake_start_process_async,
    )
    monkeypatch.setattr(downloader, "server_ready", fake_server_ready)

    port = await downloader.setup_server(model_path, "demo-model")
    await asyncio.sleep(0)

    assert port == downloader.get_server_status()["port"]
    assert downloader.get_server_status() == {
        "running": True,
        "port": port,
        "model_name": "demo-model",
        "pid": 2468,
    }
    assert start_calls == [
        (
            [
                str(downloader.executable),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--model",
                str(model_path.resolve()),
                "--alias",
                "demo-model",
                "--gpu-layers",
                "auto",
            ],
            {
                "stdout": downloader_module.asyncio.subprocess.PIPE,
                "stderr": downloader_module.asyncio.subprocess.STDOUT,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_shutdown_server_uses_shared_shutdown_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    process = _FakeServerProcess()
    calls: list[tuple[object, float]] = []

    async def fake_shutdown_process(
        proc,
        *,
        graceful_timeout,
        kill_timeout=None,
    ):
        del kill_timeout
        calls.append((proc, graceful_timeout))
        return ShutdownResult(
            command=["demo"],
            pid=process.pid,
            exited=True,
            terminated_gracefully=True,
            killed=False,
            timed_out=False,
            returncode=0,
        )

    downloader._server_process = process
    downloader._server_port = 8080
    downloader._server_model_name = "demo"
    downloader._server_log_task = cast(
        asyncio.Task[None],
        SimpleNamespace(done=lambda: True),
    )

    monkeypatch.setattr(
        downloader_module,
        "shutdown_process",
        fake_shutdown_process,
    )

    await downloader.shutdown_server()

    assert calls == [(process, 5.0)]
    assert downloader.get_server_status() == {
        "running": False,
        "port": None,
        "model_name": None,
        "pid": None,
    }


def test_force_shutdown_server_uses_shared_shutdown_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    process = _FakeServerProcess()
    calls: list[tuple[object, float, float | None]] = []

    def fake_shutdown_process_sync(proc, *, graceful_timeout, kill_timeout):
        calls.append((proc, graceful_timeout, kill_timeout))
        return ShutdownResult(
            command=["demo"],
            pid=process.pid,
            exited=True,
            terminated_gracefully=False,
            killed=True,
            timed_out=False,
            returncode=-9,
        )

    downloader._server_process = process
    downloader._server_log_task = cast(
        asyncio.Task[None],
        SimpleNamespace(done=lambda: True),
    )

    monkeypatch.setattr(
        downloader_module,
        "shutdown_process_sync",
        fake_shutdown_process_sync,
    )

    downloader.force_shutdown_server()

    assert calls == [(process, 5.0, 1.0)]
