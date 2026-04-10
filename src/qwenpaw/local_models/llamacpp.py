# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import asyncio
import logging
import multiprocessing as mp
import shutil
import socket
import tempfile
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx
from pydantic import BaseModel

from qwenpaw.constant import DEFAULT_LOCAL_PROVIDER_DIR
from qwenpaw.providers.provider import ModelInfo

from .download_manager import (
    DownloadProgressUpdate,
    DownloadProgressTracker,
    ProcessDownloadTask,
    DownloadTaskResult,
    DownloadTaskStatus,
    ProcessDownloadController,
    ProcessDownloadTaskSpec,
)
from ..utils.command_runner import (
    ManagedProcess,
    run_command_async,
    shutdown_process,
    shutdown_process_sync,
    start_command_async,
)
from ..utils import system_info
from ..utils.stdio import ensure_standard_streams

logger = logging.getLogger(__name__)


class LlamaCppServerSetupResult(BaseModel):
    """Runtime information for a started llama.cpp server."""

    port: int
    model_info: ModelInfo


class LlamaCppBackend:
    """
    QwenPaw local model backend for managing llama.cpp server installation
    and setup.
    """

    _MIN_MACOS_VERSION = (13, 3)

    def __init__(self):
        self.os_name = self._resolve_os_name()
        self.arch = self._resolve_arch()
        self.cuda_version = self._resolve_cuda_version()
        self.backend = self._resolve_backend()
        self.target_dir = DEFAULT_LOCAL_PROVIDER_DIR / "bin"
        self._context = mp.get_context("spawn")
        self._server_process: ManagedProcess | None = None
        self._server_log_task: asyncio.Task[None] | None = None
        self._server_port: int | None = None
        self._server_model_name: str | None = None
        self._server_transitioning = False
        self._progress = DownloadProgressTracker()
        self._download_controller = ProcessDownloadController(
            context=self._context,
            progress=self._progress,
        )
        atexit.register(self._shutdown_server_at_exit)

    # -----------------------------
    # Public APIs
    # -----------------------------
    @property
    def executable(self) -> Path:
        """The expected path of the llama.cpp server executable after download
        and extraction."""
        if self.os_name == "windows":
            return self.target_dir / "llama-server.exe"
        return self.target_dir / "llama-server"

    def check_llamacpp_installation(self) -> tuple[bool, str]:
        """Check if the llama.cpp server executable exists."""
        if self.executable.exists():
            return True, ""
        else:
            return False, "llama.cpp is not installed"

    def check_llamacpp_installability(self) -> tuple[bool, str]:
        """Check whether the current environment can install llama.cpp."""
        if self.os_name == "macos":
            supported, message = self._ensure_supported_macos_version()
            if not supported:
                return False, message

        try:
            self._build_filename("b0")
        except RuntimeError as exc:
            return False, str(exc)

        return True, ""

    def get_download_progress(self) -> dict[str, Any]:
        """Return the current llama.cpp download progress."""
        return self._progress.snapshot()

    def get_server_status(self) -> dict[str, Any]:
        """Return the current llama.cpp server status snapshot."""
        process = self._server_process
        running = bool(process is not None and process.returncode is None)
        return {
            "running": running,
            "port": self._server_port,
            "model_name": self._server_model_name,
            "pid": process.pid if running and process is not None else None,
        }

    def is_server_transitioning(self) -> bool:
        """Return whether the llama.cpp server is starting or stopping."""
        return self._server_transitioning

    def cancel_download(self) -> None:
        """Request cancellation of the current llama.cpp download."""
        self._download_controller.cancel()

    async def has_update(self, latest_version: str) -> bool:
        """Check if there is a newer version of llama.cpp available."""
        if not self.check_llamacpp_installation()[0]:
            return False
        try:
            current_version = int(await self.get_version())
            # strip leading 'b' in version tag
            target_version = int(latest_version[1:])
            logger.info(
                f"Current version: {current_version}, "
                f"Target version: {target_version}",
            )
            return target_version > current_version
        except Exception:
            logger.warning("Failed to check for llama.cpp updates")
            return True

    def download(
        self,
        base_url: str,
        tag: str,
        chunk_size: int = 1024 * 1024,
        timeout: int = 30,
    ) -> None:
        self.start_download(
            base_url=base_url,
            tag=tag,
            chunk_size=chunk_size,
            timeout=timeout,
        )

    def start_download(
        self,
        base_url: str,
        tag: str,
        chunk_size: int = 1024 * 1024,
        timeout: int = 30,
    ) -> None:
        """Start downloading and extracting the llama.cpp release package.

        Args:
          - chunk_size:
              Size of each read chunk
          - timeout:
              Network timeout in seconds

        Raises:
          - RuntimeError: another llama.cpp download is already in progress
          - ValueError: target_dir is an existing file path instead of a
            directory
        """
        installable, message = self.check_llamacpp_installability()
        if not installable:
            raise RuntimeError(message)
        dest_dir = self._resolve_dest_dir(self.target_dir)
        if self._is_download_active():
            raise RuntimeError(
                "A llama.cpp download is already in progress.",
            )

        staging_dir = dest_dir.parent / f".llamacpp-{uuid.uuid4().hex}"
        filename = self._build_filename(tag)
        download_url = f"{base_url}/{tag}/{filename}"
        spec = ProcessDownloadTaskSpec(
            process_name=f"qwenpaw-llamacpp-download-{staging_dir.name}",
            command=["qwenpaw-llamacpp-download", download_url],
            task=ProcessDownloadTask(
                target=type(self)._download_worker,
                payload={
                    "url": download_url,
                    "staging_dir": str(staging_dir),
                    "file_name": filename,
                    "chunk_size": chunk_size,
                    "timeout": timeout,
                    "headers": self._download_headers,
                },
                finalize_result=lambda result: self._finalize_download_result(
                    result,
                    staging_dir=staging_dir,
                    final_dir=dest_dir,
                ),
                cleanup=lambda: self._cleanup_download_path(staging_dir),
            ),
            source=download_url,
            poll_interval=0.2,
        )
        self._download_controller.start(spec)

    async def setup_server(
        self,
        model_path: Path,
        model_name: str,
        max_context_length: int | None = None,
    ) -> LlamaCppServerSetupResult:
        """Setup llama.cpp server and return the runtime port and model info.

        Args:
            model_path: Path to a local HF repo directory or GGUF file
            model_name: Name of the model to be used in the server
            max_context_length: Optional context window passed to llama.cpp
        """
        installed, message = self.check_llamacpp_installation()
        if not installed:
            raise RuntimeError(message or "llama.cpp server is not installed")
        if not model_path.exists():
            raise FileNotFoundError(f"Model path not found: {model_path}")

        resolved_model_path, resolved_mmproj_path = self._resolve_model_file(
            model_path,
        )
        model_info = self._build_model_info(
            model_name=model_name,
            resolved_mmproj_path=resolved_mmproj_path,
        )

        if (
            model_name == self._server_model_name
            and self._server_process is not None
        ):
            if self._server_process.returncode is None:
                logger.info(
                    "Requested model %s is already served on port %s",
                    model_name,
                    self._server_port,
                )
                return LlamaCppServerSetupResult(
                    port=self._server_port,
                    model_info=model_info,
                )
            else:
                logger.warning(
                    "Previous llama.cpp server process for model %s exited "
                    "unexpectedly with code %s. Restarting server.",
                    self._server_model_name,
                    self._server_process.returncode,
                )
        if self._server_process and self._server_process.returncode is None:
            await self.shutdown_server()

        self._server_transitioning = True
        port = self._find_free_port()
        process_kwargs: dict[str, Any] = {}
        if self.os_name != "windows":
            process_kwargs["start_new_session"] = True
        process = await self._create_server_process(
            resolved_model_path=resolved_model_path,
            resolved_mmproj_path=resolved_mmproj_path,
            model_name=model_name,
            port=port,
            max_context_length=max_context_length,
            process_kwargs=process_kwargs,
        )

        self._server_process = process
        self._server_port = port
        self._server_model_name = model_name
        self._server_log_task = asyncio.create_task(
            self._drain_server_logs(),
            name="llamacpp_server_logs",
        )

        try:
            logger.info("Waiting for llama.cpp server to become ready...")
            await self.server_ready()
            logger.info("llama.cpp server is ready")
        except Exception:
            await self.shutdown_server()
            raise
        finally:
            self._server_transitioning = False

        logger.info(
            "llama.cpp server started on port %s for model %s",
            port,
            model_name,
        )
        return LlamaCppServerSetupResult(
            port=port,
            model_info=model_info,
        )

    async def list_devices(self) -> list[str]:
        """List available devices for llama.cpp using
        `llama-server --list-devices`."""
        installed, message = self.check_llamacpp_installation()
        if not installed:
            raise RuntimeError(message or "llama.cpp server is not installed")

        result = await run_command_async(
            [str(self.executable), "--list-devices"],
            timeout=10,
        )
        return [
            line.strip()
            for line in result.combined_output.splitlines()
            if line.strip() and not line.startswith("ggml")
        ][1:]

    async def get_version(self) -> str:
        """get llama.cpp server version using `llama-server --version`."""
        installed, message = self.check_llamacpp_installation()
        if not installed:
            raise RuntimeError(message or "llama.cpp server is not installed")

        result = await run_command_async(
            [str(self.executable), "--version"],
            timeout=10,
        )
        lines = result.stderr_lines
        for line in lines:
            if line.startswith("version:"):
                return line[9:13]
        raise RuntimeError(
            "Unexpected version output from llama.cpp server: "
            f"{result.combined_output}",
        )

    def _is_download_active(self) -> bool:
        """Return whether the background download thread is active."""
        return self._download_controller.is_active()

    async def _create_server_process(
        self,
        resolved_model_path: Path,
        resolved_mmproj_path: Path | None,
        model_name: str,
        port: int,
        max_context_length: int | None,
        process_kwargs: dict[str, Any],
    ) -> ManagedProcess:
        command = [
            str(self.executable),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--model",
            str(resolved_model_path),
            "--alias",
            model_name,
            "--gpu-layers",
            "auto",
        ]
        if max_context_length is not None:
            command.extend(["--ctx-size", str(max_context_length)])
        if resolved_mmproj_path is not None:
            command.extend(
                [
                    "--mmproj",
                    str(resolved_mmproj_path),
                ],
            )

        logger.info(
            "Setting up llama.cpp server for model %s at path %s%s",
            model_name,
            resolved_model_path,
            (
                f" with mmproj {resolved_mmproj_path}"
                if resolved_mmproj_path is not None
                else ""
            ),
        )
        return await start_command_async(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **process_kwargs,
        )

    async def shutdown_server(self) -> None:
        """Shutdown the llama.cpp server if it's running."""
        with self._server_shutdown_context() as process:
            await self._cancel_server_log_task()

            if process and process.returncode is None:
                await shutdown_process(
                    process,
                    graceful_timeout=5.0,
                    kill_timeout=3.0,
                )

    def shutdown_server_sync(self) -> None:
        """Best-effort synchronous cleanup for shutdown and atexit paths."""
        with self._server_shutdown_context() as process:
            self._cancel_server_log_task_nowait()

            if process and process.returncode is None:
                shutdown_process_sync(
                    process,
                    graceful_timeout=5.0,
                    kill_timeout=1.0,
                )

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _resolve_dest_dir(self, dest: str | Path) -> Path:
        path = Path(dest)

        if path.exists() and not path.is_dir():
            raise ValueError("dest must be a directory path")

        return path

    def _resolve_model_file(
        self,
        model_path: Path,
    ) -> tuple[Path, Path | None]:
        if model_path.is_file():
            if model_path.suffix.lower() != ".gguf":
                raise RuntimeError(
                    f"Model file must be a .gguf file: {model_path}",
                )
            return model_path.resolve(), None

        gguf_files = sorted(
            candidate
            for candidate in model_path.rglob("*.gguf")
            if candidate.is_file()
            and not any(
                part.startswith(".")
                for part in candidate.relative_to(model_path).parts[:-1]
            )
        )
        if not gguf_files:
            raise RuntimeError(
                "Model repository at "
                f"{model_path} does not contain any .gguf files.",
            )

        mmproj_files = [
            candidate
            for candidate in gguf_files
            if candidate.name.lower().startswith("mmproj")
        ]
        model_files = [
            candidate
            for candidate in gguf_files
            if not candidate.name.lower().startswith("mmproj")
        ]

        if not model_files:
            raise RuntimeError(
                "Model repository at "
                f"{model_path} does not contain any model .gguf files.",
            )

        return (
            model_files[0].resolve(),
            mmproj_files[0].resolve() if mmproj_files else None,
        )

    @staticmethod
    def _build_model_info(
        model_name: str,
        resolved_mmproj_path: Path | None,
    ) -> ModelInfo:
        supports_multimodal = resolved_mmproj_path is not None
        return ModelInfo(
            id=model_name,
            name=model_name,
            supports_multimodal=supports_multimodal,
            # TODO: add more detailed capability flags
            supports_image=supports_multimodal,
            supports_video=False,
            probe_source="probed",
        )

    def _finalize_download_result(
        self,
        result: DownloadTaskResult,
        *,
        staging_dir: Path,
        final_dir: Path,
    ) -> tuple[DownloadTaskResult, int | None]:
        if result.status != DownloadTaskStatus.COMPLETED:
            return result, None

        try:
            if final_dir.exists():
                shutil.rmtree(final_dir)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging_dir), str(final_dir))
        except (OSError, shutil.Error) as exc:
            logger.warning(
                "Failed to finalize llama.cpp download from %s to %s: %s",
                staging_dir,
                final_dir,
                exc,
            )
            return (
                DownloadTaskResult(
                    status=DownloadTaskStatus.FAILED,
                    error=(
                        "llama.cpp download completed, but installing "
                        f"files to {final_dir} failed: {exc}"
                    ),
                ),
                None,
            )

        return (
            DownloadTaskResult(
                status=DownloadTaskStatus.COMPLETED,
                local_path=str(final_dir),
            ),
            None,
        )

    @staticmethod
    def _download_worker(payload: dict[str, Any], queue: Any) -> None:
        ensure_standard_streams()
        url = payload["url"]
        staging_dir = Path(payload["staging_dir"]).expanduser().resolve()
        file_name = payload["file_name"]
        chunk_size = int(payload["chunk_size"])
        timeout = int(payload["timeout"])
        headers = dict(payload["headers"])

        staging_dir.mkdir(parents=True, exist_ok=True)
        temp_path = staging_dir / file_name

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    total_bytes = response.headers.get("Content-Length")
                    total_bytes_int = (
                        int(total_bytes)
                        if total_bytes and total_bytes.isdigit()
                        else None
                    )
                    downloaded = 0

                    with open(temp_path, "wb") as file_obj:
                        for chunk in response.iter_bytes(
                            chunk_size=chunk_size,
                        ):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            downloaded += len(chunk)
                            queue.put(
                                DownloadProgressUpdate(
                                    downloaded_bytes=downloaded,
                                    total_bytes=total_bytes_int,
                                    source=url,
                                ).to_message(),
                            )

            LlamaCppBackend._extract_archive(
                temp_path,
                staging_dir,
            )
            temp_path.unlink(missing_ok=True)
            queue.put(
                DownloadTaskResult(
                    status=DownloadTaskStatus.COMPLETED,
                    local_path=str(staging_dir),
                ).to_message(),
            )
        except Exception as exc:
            LlamaCppBackend._cleanup_download_files(temp_path)
            error_message = LlamaCppBackend._format_download_error(exc, url)
            queue.put(
                DownloadTaskResult(
                    status=DownloadTaskStatus.FAILED,
                    error=error_message,
                ).to_message(),
            )
            logger.warning(
                "llama.cpp download failed for %s: %s",
                url,
                error_message,
            )
            return

    @staticmethod
    def _format_download_error(exc: Exception, url: str) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 404:
                return (
                    "llama.cpp download package was not found (HTTP 404). "
                    "The requested version may not exist, is no longer "
                    "available, or your hardware or operating system "
                    "version is not supported."
                )
            if status_code in {401, 403}:
                return (
                    "llama.cpp download address is unavailable or access is "
                    f"denied (HTTP {status_code}). Please verify the "
                    "requested version, or check whether your hardware or "
                    "operating system version is supported."
                )
            if status_code >= 500:
                return (
                    "llama.cpp download server is temporarily unavailable "
                    f"(HTTP {status_code}). Please try again later."
                )
            return (
                "llama.cpp download failed with an unexpected server "
                f"response (HTTP {status_code})."
            )

        if isinstance(exc, httpx.RequestError):
            return (
                "Unable to connect to the llama.cpp download server. "
                f"Request URL: {url}."
            )

        return f"llama.cpp download failed: {exc}"

    @staticmethod
    def _find_free_port(host: str = "127.0.0.1") -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    async def server_ready(
        self,
        timeout: float = 120.0,
    ) -> bool:
        """Check if the llama.cpp server is ready."""
        if not self._server_process or self._server_port is None:
            raise RuntimeError("llama.cpp server process was not created")

        health_url = f"http://127.0.0.1:{self._server_port}/health"
        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._server_process.returncode is not None:
                    raise RuntimeError(
                        "llama.cpp server exited before becoming ready",
                    )
                try:
                    response = await client.get(health_url)
                    if response.status_code < 500:
                        return True

                    logger.info(
                        "llama.cpp health check returned %s while "
                        "waiting for %s",
                        response.status_code,
                        health_url,
                    )
                except httpx.HTTPError as exc:
                    logger.info(
                        "llama.cpp health check failed for %s: %s",
                        health_url,
                        exc,
                    )

                await asyncio.sleep(1)
        raise RuntimeError("Timed out waiting for llama.cpp server to start")

    async def _drain_server_logs(self) -> None:
        if not self._server_process or not self._server_process.stdout:
            return

        while True:
            line = await self._server_process.stdout.readline()
            if not line:
                break
            logger.debug(
                "llama-server: %s",
                line.decode("utf-8", errors="replace").rstrip(),
            )

    async def _cancel_server_log_task(self) -> None:
        task = self._server_log_task
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def _cancel_server_log_task_nowait(self) -> None:
        task = self._server_log_task
        if task and not task.done():
            task.cancel()

    @contextmanager
    def _server_shutdown_context(self) -> Iterator[ManagedProcess | None]:
        self._server_transitioning = True
        process = self._server_process
        try:
            yield process
        finally:
            self._reset_server_state()

    def _reset_server_state(self) -> None:
        self._server_process = None
        self._server_log_task = None
        self._server_port = None
        self._server_model_name = None
        self._server_transitioning = False

    def _shutdown_server_at_exit(self) -> None:
        with suppress(Exception):
            self.shutdown_server_sync()

    @staticmethod
    def _extract_archive(
        archive_path: Path,
        dest_dir: Path,
    ) -> None:
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{archive_path.stem}-",
                dir=str(dest_dir.parent),
            ),
        )
        try:
            shutil.unpack_archive(str(archive_path), str(staging_dir))
            LlamaCppBackend._merge_extracted_content(
                staging_dir,
                dest_dir,
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    @staticmethod
    def _merge_extracted_content(
        staging_dir: Path,
        dest_dir: Path,
    ) -> None:
        # There are only two expected archive structures:
        # 1) All files directly in the root of the archive
        # 2) All files in a single top-level directory (e.g. "llama-xx/")
        extracted_entries = list(staging_dir.iterdir())
        source_root = staging_dir
        if len(extracted_entries) == 1 and extracted_entries[0].is_dir():
            source_root = extracted_entries[0]

        for item in source_root.iterdir():
            if not item.is_file():
                raise RuntimeError(
                    "Unexpected directory structure in llama.cpp archive: "
                    f"{item}",
                )
            shutil.copy2(item, dest_dir / item.name)

    @staticmethod
    def _cleanup_download_files(
        *paths: Path,
    ) -> None:
        for path in paths:
            with suppress(FileNotFoundError):
                path.unlink(missing_ok=True)

    @staticmethod
    def _cleanup_download_path(path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return
        path.unlink(missing_ok=True)

    @property
    def _download_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        }

    def _resolve_os_name(self) -> str:
        os_name = system_info.get_os_name()
        if os_name in ("windows", "macos", "linux"):
            return os_name
        raise RuntimeError(f"Unsupported OS: {os_name}")

    def _resolve_arch(self) -> str:
        arch = system_info.get_architecture()
        if arch in ("x64", "arm64"):
            return arch
        raise RuntimeError(f"Unsupported architecture: {arch}")

    def _ensure_supported_macos_version(self) -> tuple[bool, str]:
        if self.os_name != "macos":
            return True, ""
        macos_version = system_info.get_macos_version()
        if macos_version is None:
            logger.warning("Unable to determine macOS version for llama.cpp")
            return False, "Unknown macOS version"

        if macos_version < self._MIN_MACOS_VERSION:
            current_version = ".".join(str(part) for part in macos_version)
            min_version = ".".join(
                str(part) for part in self._MIN_MACOS_VERSION
            )
            return (
                False,
                f"Unsupported macOS version: {current_version} "
                f"(requires {min_version} or later)",
            )
        return True, ""

    def _resolve_backend(self) -> str:
        # On macOS and Linux, only CPU backend is supported
        if self.os_name in ("macos", "linux"):
            return "cpu"

        # On Windows, check for CUDA support
        if self.cuda_version is not None:
            return "cuda"
        return "cpu"

    def _resolve_cuda_version(self) -> Optional[str]:
        if self.os_name != "windows":
            return None

        cuda_version = system_info.get_cuda_version()
        if cuda_version is None:
            return None

        parts = cuda_version.split(".")
        major = parts[0]
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        if major == "12":
            return "12.4" if minor >= 4 else None
        if major == "13":
            return "13.1"
        return None

    def _build_filename(self, tag: str) -> str:
        if self.os_name == "macos":
            return f"llama-{tag}-bin-macos-{self.arch}.tar.gz"

        if self.os_name == "linux":
            return f"llama-{tag}-bin-ubuntu-{self.arch}.tar.gz"

        if self.os_name == "windows":
            if self.backend == "cuda":
                if self.arch != "x64":
                    raise RuntimeError(
                        "Windows CUDA package is only supported for x64.",
                    )
                return (
                    f"llama-{tag}-bin-win-cuda-"
                    f"{self.cuda_version}-{self.arch}.zip"
                )
            return f"llama-{tag}-bin-win-cpu-{self.arch}.zip"

        raise RuntimeError(f"Unsupported OS: {self.os_name}")
