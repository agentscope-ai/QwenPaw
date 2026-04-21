# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import io
import socket
import tarfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

import qwenpaw.local_models.llamacpp as downloader_module
from qwenpaw.constant import DEFAULT_LOCAL_PROVIDER_DIR
from qwenpaw.local_models.download_manager import (
    DownloadTaskResult,
    DownloadTaskStatus,
)
from qwenpaw.utils.command_runner import (
    CommandExecutionError,
    CommandResult,
    ShutdownResult,
)
from qwenpaw.local_models.llamacpp import LlamaCppBackend


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
        archive.writestr("llama-b1234/bin/server.exe", "zip-binary")
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
        for name, content in {
            "llama-b1234/server": b"tar-binary",
            "llama-b1234/llama-cli": b"cli-binary",
        }.items():
            info = tarfile.TarInfo(name=name)
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
    return LlamaCppBackend()


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

    llamacpp = LlamaCppBackend()
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

    downloader = LlamaCppBackend()

    assert downloader.os_name == "macos"


@pytest.mark.asyncio
async def test_list_devices_returns_trimmed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    calls: list[list[str]] = []

    base_stderr = """
ggml_metal_device_init: tensor API disabled for pre-M5 and pre-A19 devices
ggml_metal_library_init: using embedded metal library
ggml_metal_library_init: loaded in 0.030 sec
ggml_metal_rsets_init: creating a residency set collection (keep_alive = 180 s)
ggml_metal_device_init: GPU name:   MTL0
ggml_metal_device_init: GPU family: MTLGPUFamilyApple7  (1007)
ggml_metal_device_init: GPU family: MTLGPUFamilyCommon3 (3003)
ggml_metal_device_init: GPU family: MTLGPUFamilyMetal3  (5001)
ggml_metal_device_init: simdgroup reduction   = true
ggml_metal_device_init: simdgroup matrix mul. = true
ggml_metal_device_init: has unified memory    = true
ggml_metal_device_init: has bfloat            = true
ggml_metal_device_init: has tensor            = false
ggml_metal_device_init: use residency sets    = true
ggml_metal_device_init: use shared buffers    = true
ggml_metal_device_init: recommendedMaxWorkingSetSize  = 11453.25 MB
Available devices:
"""

    async def fake_run_command_async(
        command: list[str],
        **_kwargs: Any,
    ) -> CommandResult:
        del _kwargs
        calls.append(command)
        return CommandResult(
            command=command,
            returncode=0,
            stdout="",
            stderr=base_stderr,
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

    assert await downloader.list_devices() == []
    assert calls == [[str(downloader.executable), "--list-devices"]]

    base_stderr = (
        base_stderr
        + """
  MTL0: Apple M1 Pro (10922 MiB, 10922 MiB free)
  BLAS: Accelerate (0 MiB, 0 MiB free)"""
    )

    assert await downloader.list_devices() == [
        "MTL0: Apple M1 Pro (10922 MiB, 10922 MiB free)",
        "BLAS: Accelerate (0 MiB, 0 MiB free)",
    ]


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
            stderr="""
ggml_metal_device_init: tensor API disabled for pre-M5 and pre-A19 devices
ggml_metal_library_init: using embedded metal library
ggml_metal_library_init: loaded in 0.009 sec
ggml_metal_rsets_init: creating a residency set collection (keep_alive = 180 s)
ggml_metal_device_init: GPU name:   MTL0
ggml_metal_device_init: GPU family: MTLGPUFamilyApple7  (1007)
ggml_metal_device_init: GPU family: MTLGPUFamilyCommon3 (3003)
ggml_metal_device_init: GPU family: MTLGPUFamilyMetal3  (5001)
ggml_metal_device_init: simdgroup reduction   = true
ggml_metal_device_init: simdgroup matrix mul. = true
ggml_metal_device_init: has unified memory    = true
ggml_metal_device_init: has bfloat            = true
ggml_metal_device_init: has tensor            = false
ggml_metal_device_init: use residency sets    = true
ggml_metal_device_init: use shared buffers    = true
ggml_metal_device_init: recommendedMaxWorkingSetSize  = 11453.25 MB
version: 8514 (406f4e3f6)
built with AppleClang 15.0.0.15000309 for Darwin arm64""",
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

    assert await downloader.get_version() == "8514"


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

    downloader = LlamaCppBackend()

    assert downloader.cuda_version == expected


def _patch_httpx_client(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    *,
    chunk_delay: float = 0.0,
    status_code: int = 200,
    exc: Exception | None = None,
) -> _FakeHttpxClient:
    fake_client = _FakeHttpxClient(
        payload,
        chunk_delay=chunk_delay,
        status_code=status_code,
        exc=exc,
    )
    monkeypatch.setattr(
        downloader_module.httpx,
        "Client",
        lambda **kwargs: fake_client,
    )
    return fake_client


class _FakeDownloadController:
    def __init__(self) -> None:
        self.started_spec = None
        self.cancel_called = False
        self.active = False

    def start(self, spec) -> None:
        self.started_spec = spec
        self.active = True

    def cancel(self) -> None:
        self.cancel_called = True
        self.active = False

    def is_active(self) -> bool:
        return self.active


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


def test_start_download_delegates_to_process_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    downloader.target_dir = tmp_path / "install"
    controller = _FakeDownloadController()
    downloader.__dict__["_download_controller"] = controller

    downloader.start_download(
        base_url="https://example.com/releases",
        tag="b1234",
        chunk_size=64,
        timeout=15,
    )

    assert controller.started_spec is not None
    assert controller.started_spec.command == [
        "qwenpaw-llamacpp-download",
        "https://example.com/releases/b1234/"
        "llama-b1234-bin-ubuntu-x64.tar.gz",
    ]
    assert controller.started_spec.source == (
        "https://example.com/releases/b1234/"
        "llama-b1234-bin-ubuntu-x64.tar.gz"
    )
    assert controller.started_spec.task.payload["chunk_size"] == 64
    assert controller.started_spec.task.payload["timeout"] == 15
    assert controller.started_spec.task.payload["file_name"] == (
        "llama-b1234-bin-ubuntu-x64.tar.gz"
    )


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
        downloader.download(
            base_url="https://example.com/releases",
            tag="b1234",
        )


def test_download_worker_emits_failure_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    request = httpx.Request("GET", "https://example.com/fail")
    download_url = (
        "https://example.com/releases/b1234/llama-b1234-bin-win-cpu-x64.zip"
    )
    _patch_httpx_client(
        monkeypatch,
        b"",
        exc=httpx.ReadError("boom", request=request),
    )

    messages: list[dict[str, object]] = []

    class _Queue:
        def put(self, item):
            messages.append(item)

    downloader._download_worker(
        {
            "url": download_url,
            "staging_dir": str(tmp_path / "failure"),
            "file_name": "llama-b1234-bin-win-cpu-x64.zip",
            "chunk_size": 64,
            "timeout": 30,
            "headers": downloader._download_headers,
        },
        _Queue(),
    )

    assert messages[-1]["type"] == "result"
    assert isinstance(messages[-1]["payload"], dict)
    assert messages[-1]["payload"]["status"] == "failed"
    assert messages[-1]["payload"]["error"] == (
        "Unable to connect to the llama.cpp download server. "
        f"Request URL: {download_url}."
    )


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (
            403,
            "llama.cpp download address is unavailable or access is denied "
            "(HTTP 403). Please verify the requested version, or check "
            "whether your hardware or operating system version is "
            "supported.",
        ),
        (
            404,
            "llama.cpp download package was not found (HTTP 404). The "
            "requested version may not exist, is no longer available, or "
            "your hardware or operating system version is not supported.",
        ),
    ],
)
def test_download_worker_maps_http_status_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status_code: int,
    expected_error: str,
) -> None:
    downloader = _build_downloader(monkeypatch)
    download_url = (
        "https://example.com/releases/b1234/llama-b1234-bin-win-cpu-x64.zip"
    )
    _patch_httpx_client(
        monkeypatch,
        b"",
        status_code=status_code,
    )

    messages: list[dict[str, object]] = []

    class _Queue:
        def put(self, item):
            messages.append(item)

    downloader._download_worker(
        {
            "url": download_url,
            "staging_dir": str(tmp_path / f"failure-{status_code}"),
            "file_name": "llama-b1234-bin-win-cpu-x64.zip",
            "chunk_size": 64,
            "timeout": 30,
            "headers": downloader._download_headers,
        },
        _Queue(),
    )

    assert messages[-1]["type"] == "result"
    assert isinstance(messages[-1]["payload"], dict)
    assert messages[-1]["payload"]["status"] == "failed"
    assert messages[-1]["payload"]["error"] == expected_error


def test_cancel_download_delegates_to_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    controller = _FakeDownloadController()
    downloader.__dict__["_download_controller"] = controller

    downloader.cancel_download()

    assert controller.cancel_called is True


def test_finalize_download_result_moves_staging_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    staging_dir = tmp_path / "staging"
    final_dir = tmp_path / "final"
    staging_dir.mkdir()
    (staging_dir / "bin").mkdir()
    (staging_dir / "bin" / "server").write_text("tar-binary")

    result, downloaded_bytes = downloader._finalize_download_result(
        DownloadTaskResult(
            status=DownloadTaskStatus.COMPLETED,
            local_path=str(staging_dir),
        ),
        staging_dir=staging_dir,
        final_dir=final_dir,
    )

    assert result.local_path == str(final_dir)
    assert downloaded_bytes is None
    assert not staging_dir.exists()
    assert (final_dir / "bin" / "server").read_text() == "tar-binary"


def test_finalize_download_result_returns_failed_result_on_fs_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    staging_dir = tmp_path / "staging"
    final_dir = tmp_path / "final"
    staging_dir.mkdir()
    (staging_dir / "bin").mkdir()
    (staging_dir / "bin" / "server").write_text("tar-binary")

    def _raise_move_error(src: str, dst: str) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(downloader_module.shutil, "move", _raise_move_error)

    result, downloaded_bytes = downloader._finalize_download_result(
        DownloadTaskResult(
            status=DownloadTaskStatus.COMPLETED,
            local_path=str(staging_dir),
        ),
        staging_dir=staging_dir,
        final_dir=final_dir,
    )

    assert result.status == DownloadTaskStatus.FAILED
    assert result.local_path is None
    assert downloaded_bytes is None
    assert result.error == (
        "llama.cpp download completed, but installing files to "
        f"{final_dir} failed: Permission denied"
    )
    assert staging_dir.exists()
    assert not final_dir.exists()


def test_download_worker_flattens_single_top_level_archive_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    staging_dir = tmp_path / "flattened-install"
    download_url = (
        "https://example.com/releases/b1234/"
        "llama-b1234-bin-ubuntu-x64.tar.gz"
    )
    _patch_httpx_client(
        monkeypatch,
        _make_tar_gz_payload_with_top_level_dir(),
    )

    messages: list[dict[str, object]] = []

    class _Queue:
        def put(self, item):
            messages.append(item)

    downloader._download_worker(
        {
            "url": download_url,
            "staging_dir": str(staging_dir),
            "file_name": "llama-b1234-bin-ubuntu-x64.tar.gz",
            "chunk_size": 64,
            "timeout": 30,
            "headers": downloader._download_headers,
        },
        _Queue(),
    )

    assert (staging_dir / "server").read_text() == "tar-binary"
    assert (staging_dir / "llama-cli").read_text() == "cli-binary"
    assert not (staging_dir / "llama-b1234").exists()
    assert isinstance(messages[-1]["payload"], dict)
    assert messages[-1]["payload"]["status"] == "completed"


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

    async def fake_start_command_async(command, **kwargs):
        start_calls.append((list(command), kwargs))
        return _FakeStartedProcess()

    async def fake_server_ready(*_args, **_kwargs) -> bool:
        return True

    downloader.os_name = "windows"
    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader_module,
        "start_command_async",
        fake_start_command_async,
    )
    monkeypatch.setattr(downloader, "server_ready", fake_server_ready)

    setup_result = await downloader.setup_server(model_path, "demo-model")
    await asyncio.sleep(0)

    assert setup_result.port == downloader.get_server_status()["port"]
    assert setup_result.model_info.model_dump() == {
        "id": "demo-model",
        "is_free": False,
        "name": "demo-model",
        "supports_multimodal": False,
        "supports_image": False,
        "supports_video": False,
        "probe_source": "probed",
        "generate_kwargs": {},
    }
    assert downloader.get_server_status() == {
        "running": True,
        "port": setup_result.port,
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
                str(setup_result.port),
                "--model",
                str(model_path.resolve()),
                "--alias",
                "demo-model",
                "--log-file",
                str(DEFAULT_LOCAL_PROVIDER_DIR / "logs" / "llama-server.log"),
                "--gpu-layers",
                "auto",
            ],
            {
                "stdout": downloader_module.asyncio.subprocess.PIPE,
                "stderr": downloader_module.asyncio.subprocess.STDOUT,
            },
        ),
    ]


def test_resolve_model_file_returns_single_model_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    model_dir = tmp_path / "text-model"
    model_dir.mkdir()
    model_file = model_dir / "demo-model.gguf"
    model_file.write_text("model")

    resolved_model, resolved_mmproj = downloader._resolve_model_file(
        model_dir,
    )

    assert resolved_model == model_file.resolve()
    assert resolved_mmproj is None


def test_resolve_model_file_returns_model_and_mmproj(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    model_dir = tmp_path / "vision-model"
    model_dir.mkdir()
    mmproj_file = model_dir / "MMPROJ-F16.gguf"
    model_file = model_dir / "qwen2vl-model.gguf"
    mmproj_file.write_text("mmproj")
    model_file.write_text("model")

    resolved_model, resolved_mmproj = downloader._resolve_model_file(
        model_dir,
    )

    assert resolved_model == model_file.resolve()
    assert resolved_mmproj == mmproj_file.resolve()


def test_resolve_model_file_rejects_mmproj_only_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    model_dir = tmp_path / "broken-model"
    model_dir.mkdir()
    (model_dir / "mmproj-model-f16.gguf").write_text("mmproj")

    with pytest.raises(RuntimeError, match="does not contain any model"):
        downloader._resolve_model_file(model_dir)


@pytest.mark.asyncio
async def test_setup_server_passes_mmproj_argument(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    downloader = _build_downloader(monkeypatch)
    model_dir = tmp_path / "vision-model"
    model_dir.mkdir()
    model_file = model_dir / "model-q4.gguf"
    mmproj_file = model_dir / "mmproj-BF16.gguf"
    model_file.write_text("model")
    mmproj_file.write_text("mmproj")
    start_calls: list[tuple[list[str], dict[str, Any]]] = []

    class _FakeAsyncStdout:
        async def readline(self) -> bytes:
            return b""

    class _FakeStartedProcess:
        def __init__(self) -> None:
            self.pid = 1357
            self.stdout = _FakeAsyncStdout()
            self.returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    async def fake_start_command_async(command, **kwargs):
        start_calls.append((list(command), kwargs))
        return _FakeStartedProcess()

    async def fake_server_ready(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader_module,
        "start_command_async",
        fake_start_command_async,
    )
    monkeypatch.setattr(downloader, "server_ready", fake_server_ready)

    setup_result = await downloader.setup_server(model_dir, "vision-model")
    await asyncio.sleep(0)

    assert setup_result.model_info.model_dump() == {
        "id": "vision-model",
        "is_free": False,
        "name": "vision-model",
        "supports_multimodal": True,
        "supports_image": True,
        "supports_video": False,
        "probe_source": "probed",
        "generate_kwargs": {},
    }

    assert start_calls == [
        (
            [
                str(downloader.executable),
                "--host",
                "127.0.0.1",
                "--port",
                str(setup_result.port),
                "--model",
                str(model_file.resolve()),
                "--alias",
                "vision-model",
                "--log-file",
                str(
                    DEFAULT_LOCAL_PROVIDER_DIR / "logs" / "llama-server.log",
                ),
                "--gpu-layers",
                "auto",
                "--mmproj",
                str(mmproj_file.resolve()),
            ],
            {
                "stdout": downloader_module.asyncio.subprocess.PIPE,
                "stderr": downloader_module.asyncio.subprocess.STDOUT,
                "start_new_session": True,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_setup_server_uses_requested_port(
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
            self.pid = 8642
            self.stdout = _FakeAsyncStdout()
            self.returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    async def fake_start_command_async(command, **kwargs):
        start_calls.append((list(command), kwargs))
        return _FakeStartedProcess()

    async def fake_server_ready(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        downloader,
        "check_llamacpp_installation",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        downloader,
        "_is_port_available",
        lambda requested_port: requested_port == 43110,
    )
    monkeypatch.setattr(
        downloader_module,
        "start_command_async",
        fake_start_command_async,
    )
    monkeypatch.setattr(downloader, "server_ready", fake_server_ready)

    setup_result = await downloader.setup_server(
        model_path,
        "demo-model",
        port=43110,
    )
    await asyncio.sleep(0)

    assert setup_result.port == 43110
    assert start_calls == [
        (
            [
                str(downloader.executable),
                "--host",
                "127.0.0.1",
                "--port",
                "43110",
                "--model",
                str(model_path.resolve()),
                "--alias",
                "demo-model",
                "--log-file",
                str(DEFAULT_LOCAL_PROVIDER_DIR / "logs" / "llama-server.log"),
                "--gpu-layers",
                "auto",
            ],
            {
                "stdout": downloader_module.asyncio.subprocess.PIPE,
                "stderr": downloader_module.asyncio.subprocess.STDOUT,
                "start_new_session": True,
            },
        ),
    ]


def test_resolve_server_port_rejects_unavailable_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloader = _build_downloader(monkeypatch)
    monkeypatch.setattr(
        downloader,
        "_is_port_available",
        lambda requested_port: False,
    )

    with pytest.raises(ValueError, match="43110"):
        downloader._resolve_server_port(43110)


def test_is_port_available_uses_exclusive_bind_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSocket:
        def __init__(self) -> None:
            self.setsockopt_calls: list[tuple[int, int, int]] = []
            self.bound_address: tuple[str, int] | None = None

        def setsockopt(self, level: int, option: int, value: int) -> None:
            self.setsockopt_calls.append((level, option, value))

        def bind(self, address: tuple[str, int]) -> None:
            self.bound_address = address

        def __enter__(self) -> Any:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    fake_socket = _FakeSocket()
    exclusive_addr_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", 0x4)

    monkeypatch.setattr(
        downloader_module.system_info,
        "get_os_name",
        lambda: "windows",
    )
    monkeypatch.setattr(
        downloader_module.socket,
        "SO_EXCLUSIVEADDRUSE",
        exclusive_addr_use,
        raising=False,
    )
    monkeypatch.setattr(
        downloader_module.socket,
        "socket",
        lambda *_args, **_kwargs: fake_socket,
    )

    assert LlamaCppBackend._is_port_available(43110) is True
    assert fake_socket.bound_address == ("127.0.0.1", 43110)
    assert fake_socket.setsockopt_calls == [
        (socket.SOL_SOCKET, exclusive_addr_use, 1),
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

    downloader._server_process = cast(Any, process)
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

    downloader._server_process = cast(Any, process)
    downloader._server_log_task = cast(
        asyncio.Task[None],
        SimpleNamespace(done=lambda: True),
    )

    monkeypatch.setattr(
        downloader_module,
        "shutdown_process_sync",
        fake_shutdown_process_sync,
    )

    downloader.shutdown_server_sync()

    assert calls == [(process, 5.0, 1.0)]
