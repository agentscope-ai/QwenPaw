# -*- coding: utf-8 -*-
from __future__ import annotations

import atexit
import asyncio
import logging
import os
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional

import httpx

from copaw.constant import DEFAULT_LOCAL_PROVIDER_DIR

from .download_manager import (
    apply_download_result,
    begin_download_task,
    DownloadProgressTracker,
    DownloadTaskResult,
    DownloadTaskStatus,
)
from ..utils import system_info

logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
    pass


class _ThreadedProcessStdout:
    """Async adapter for a blocking subprocess stdout stream."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def readline(self) -> bytes:
        return await asyncio.to_thread(self._stream.readline)


class _ThreadedServerProcess:
    """Minimal async-compatible wrapper around subprocess.Popen."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdout = (
            _ThreadedProcessStdout(process.stdout)
            if process.stdout is not None
            else None
        )

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()


class LlamaCppBackend:
    """
    CoPaw local model backend for managing llama.cpp server installation
    and setup.
    """

    def __init__(self, base_url: str, release_tag: str):
        self.base_url = base_url.rstrip("/")
        self.release_tag = release_tag

        self.os_name = self._resolve_os_name()
        self.arch = self._resolve_arch()
        self.cuda_version = self._resolve_cuda_version()
        self.backend = self._resolve_backend()
        self.target_dir = DEFAULT_LOCAL_PROVIDER_DIR / "bin"
        self._server_process: Any | None = None
        self._server_log_task: asyncio.Task[None] | None = None
        self._server_port: int | None = None
        self._server_model_name: str | None = None
        self._server_transitioning = False
        self._server_owns_process_group = False
        self._download_lock = threading.Lock()
        self._download_thread: threading.Thread | None = None
        self._download_cancel_event: threading.Event | None = None
        self._progress = DownloadProgressTracker()
        atexit.register(self._shutdown_server_at_exit)

    # -----------------------------
    # Public APIs
    # -----------------------------
    @property
    def download_url(self) -> str:
        """Get the download URL for the current environment configuration."""
        filename = self._build_filename()
        base_url = self.base_url
        return f"{base_url}/{self.release_tag}/{filename}"

    @property
    def executable(self) -> Path:
        """The expected path of the llama.cpp server executable after download
        and extraction."""
        if self.os_name == "windows":
            return self.target_dir / "llama-server.exe"
        return self.target_dir / "llama-server"

    def check_llamacpp_installation(self) -> bool:
        """Check if the llama.cpp server executable exists."""
        return self.executable.exists()

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
        thread: threading.Thread | None = None
        with self._download_lock:
            if not self._is_download_active():
                return
            if self._download_cancel_event is None:
                return
            self._download_cancel_event.set()
            self._progress.mark_canceling()
            thread = self._download_thread

        if thread is not None:
            thread.join(timeout=5)

    def download(
        self,
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
        self._start_download(
            self.target_dir,
            chunk_size=chunk_size,
            timeout=timeout,
        )

    async def setup_server(self, model_path: Path, model_name: str) -> int:
        """Setup llama.cpp server, and return the port it's running on.

        Args:
            model_path: Path to a local HF repo directory or GGUF file
            model_name: Name of the model to be used in the server
        """
        if not self.check_llamacpp_installation():
            raise RuntimeError("llama.cpp server is not installed")
        if not model_path.exists():
            raise FileNotFoundError(f"Model path not found: {model_path}")

        if (
            model_name == self._server_model_name
            and self._server_process is not None
        ):
            if self._server_process.returncode is None:
                logger.info(
                    "Requested model %s is already served by llama.cpp on "
                    "port %s",
                    model_name,
                    self._server_port,
                )
                return self._server_port  # type: ignore[return-value]
            else:
                logger.warning(
                    "Previous llama.cpp server process for model %s exited "
                    "unexpectedly with code %s. Restarting server.",
                    self._server_model_name,
                    self._server_process.returncode,
                )

        resolved_model_path = self._resolve_model_file(model_path)
        if self._server_process and self._server_process.returncode is None:
            await self.shutdown_server()

        self._server_transitioning = True
        port = self._find_free_port()
        process_kwargs: dict[str, Any] = {}
        if os.name != "nt":
            process_kwargs["start_new_session"] = True
        process = await self._create_server_process(
            resolved_model_path=resolved_model_path,
            model_name=model_name,
            port=port,
            process_kwargs=process_kwargs,
        )

        self._server_process = process
        self._server_port = port
        self._server_model_name = model_name
        self._server_owns_process_group = bool(process_kwargs)
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
        return port

    def _is_download_active(self) -> bool:
        """Return whether the background download thread is active."""
        return (
            self._download_thread is not None
            and self._download_thread.is_alive()
        )

    async def _create_server_process(
        self,
        resolved_model_path: Path,
        model_name: str,
        port: int,
        process_kwargs: dict[str, Any],
    ) -> Any:
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
        ]
        try:
            logger.info(
                "Setting up llama.cpp server for model %s at path %s",
                model_name,
                resolved_model_path,
            )
            return await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **process_kwargs,
            )
        except NotImplementedError:
            if os.name != "nt":
                raise
            logger.warning(
                "Async subprocess creation is unavailable on this Windows "
                "event loop; falling back to threaded subprocess launch.",
            )
            return await asyncio.to_thread(
                self._create_threaded_server_process,
                command,
            )

    def _create_threaded_server_process(
        self,
        command: list[str],
    ) -> _ThreadedServerProcess:
        process = subprocess.Popen(  # pylint: disable=consider-using-with
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return _ThreadedServerProcess(process)

    async def shutdown_server(self) -> None:
        """Shutdown the llama.cpp server if it's running."""
        self._server_transitioning = True
        await self._cancel_server_log_task()

        process = self._server_process
        if process and process.returncode is None:
            self._terminate_server_process()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._kill_server_process()
                await process.wait()

        self._reset_server_state()

    def force_shutdown_server(self) -> None:
        """Best-effort synchronous cleanup for shutdown and atexit paths."""
        self._server_transitioning = True
        self._cancel_server_log_task_nowait()

        process = self._server_process
        if process and process.returncode is None:
            self._terminate_server_process()
            if not self._wait_for_process_exit(process.pid, timeout=5.0):
                self._kill_server_process()
                self._wait_for_process_exit(process.pid, timeout=1.0)

        self._reset_server_state()

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _resolve_dest_dir(self, dest: str | Path) -> Path:
        path = Path(dest)

        if path.exists() and not path.is_dir():
            raise ValueError("dest must be a directory path")

        return path

    def _resolve_model_file(self, model_path: Path) -> Path:
        if model_path.is_file():
            if model_path.suffix.lower() != ".gguf":
                raise RuntimeError(
                    f"Model file must be a .gguf file: {model_path}",
                )
            return model_path.resolve()

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
        return gguf_files[0].resolve()

    def _start_download(
        self,
        dest: str | Path,
        chunk_size: int = 1024 * 1024,
        timeout: int = 30,
    ) -> None:
        """Start downloading llama.cpp in a background thread."""
        dest_dir = self._resolve_dest_dir(dest)
        with self._download_lock:
            if self._is_download_active():
                raise RuntimeError(
                    "A llama.cpp download is already in progress.",
                )

            self._download_cancel_event = threading.Event()
            begin_download_task(
                self._progress,
                source=self.download_url,
            )
            self._download_thread = threading.Thread(
                target=self._run_download_worker,
                args=(
                    dest_dir,
                    chunk_size,
                    timeout,
                ),
                name="copaw-llamacpp-download",
                daemon=True,
            )
            self._download_thread.start()

    def _run_download_worker(
        self,
        dest: str | Path,
        chunk_size: int,
        timeout: int,
    ) -> None:
        result: DownloadTaskResult
        try:
            local_path = self._download_sync(
                dest,
                chunk_size=chunk_size,
                timeout=timeout,
            )
            result = DownloadTaskResult(
                status=DownloadTaskStatus.COMPLETED,
                local_path=str(local_path),
            )
        except DownloadCancelled as exc:
            result = DownloadTaskResult(
                status=DownloadTaskStatus.CANCELLED,
                error=str(exc),
            )
        except (OSError, RuntimeError, ValueError, shutil.Error) as exc:
            result = DownloadTaskResult(
                status=DownloadTaskStatus.FAILED,
                error=str(exc),
            )
        with self._download_lock:
            self._download_thread = None
            self._download_cancel_event = None
        apply_download_result(self._progress, result)

    def _download_sync(
        self,
        dest: str | Path,
        chunk_size: int = 1024 * 1024,
        timeout: int = 30,
    ) -> Path:
        """Perform the blocking download and extraction workflow."""
        dest_dir = self._resolve_dest_dir(dest)
        url = self.download_url
        file_name = url.rsplit("/", 1)[-1]
        dest_dir.mkdir(parents=True, exist_ok=True)
        temp_file_fd, temp_file_name = tempfile.mkstemp(
            prefix="copaw-download-",
            suffix=f"-{file_name}",
            dir=str(dest_dir),
        )
        os.close(temp_file_fd)
        temp_path = Path(temp_file_name)

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "llama-release-downloader/1.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                total_bytes = response.headers.get("Content-Length")
                total_bytes_int = (
                    int(total_bytes)
                    if (total_bytes and total_bytes.isdigit())
                    else None
                )

                downloaded = 0

                with open(temp_path, "wb") as f:
                    while True:
                        if self._is_download_cancelled():
                            raise DownloadCancelled(
                                "Download cancelled by user.",
                            )

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)

                        self._progress.update_downloaded(
                            downloaded,
                            total_bytes=total_bytes_int,
                            source=url,
                        )

                if self._is_download_cancelled():
                    raise DownloadCancelled("Download cancelled by user.")

                self._extract_archive(
                    temp_path,
                    dest_dir,
                    archive_name=file_name,
                )
                temp_path.unlink(missing_ok=True)

                self._progress.update_downloaded(
                    downloaded,
                    total_bytes=total_bytes_int,
                    source=url,
                )

                return dest_dir

        except DownloadCancelled:
            self._cleanup_download_files(temp_path)
            raise
        except Exception:
            self._cleanup_download_files(temp_path)
            raise

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
                        "llama.cpp health check returned %s "
                        "while waiting for %s",
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

    def _terminate_server_process(self) -> None:
        process = self._server_process
        if process is None or process.returncode is not None:
            return

        if self._server_owns_process_group and os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            return

        with suppress(ProcessLookupError):
            process.terminate()

    def _kill_server_process(self) -> None:
        process = self._server_process
        if process is None or process.returncode is not None:
            return

        if self._server_owns_process_group and os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return

        with suppress(ProcessLookupError):
            process.kill()

    def _wait_for_process_exit(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if not self._is_pid_running(pid):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_for = min(0.1, remaining)
            threading.Event().wait(sleep_for)
        return not self._is_pid_running(pid)

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if os.name == "nt":
            try:
                output = subprocess.check_output(
                    ["tasklist", "/fi", f"PID eq {pid}"],
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False
            return str(pid) in output

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _reset_server_state(self) -> None:
        self._server_process = None
        self._server_log_task = None
        self._server_port = None
        self._server_model_name = None
        self._server_transitioning = False
        self._server_owns_process_group = False

    def _shutdown_server_at_exit(self) -> None:
        with suppress(Exception):
            self.force_shutdown_server()

    def _extract_archive(
        self,
        archive_path: Path,
        dest_dir: Path,
        archive_name: str | None = None,
    ) -> None:
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{archive_path.stem}-",
                dir=str(dest_dir.parent),
            ),
        )
        try:
            shutil.unpack_archive(str(archive_path), str(staging_dir))
            self._merge_extracted_content(
                staging_dir,
                dest_dir,
                archive_name or archive_path.name,
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _merge_extracted_content(
        self,
        staging_dir: Path,
        dest_dir: Path,
        archive_name: str,
    ) -> None:
        extracted_entries = list(staging_dir.iterdir())
        source_root = staging_dir
        if (
            len(extracted_entries) == 1
            and extracted_entries[0].is_dir()
            and self._should_flatten_archive_root(
                extracted_entries[0],
                archive_name,
            )
        ):
            source_root = extracted_entries[0]

        for item in source_root.iterdir():
            self._merge_path(item, dest_dir / item.name)

    @staticmethod
    def _should_flatten_archive_root(
        root_dir: Path,
        archive_name: str,
    ) -> bool:
        dir_name = root_dir.name
        archive_names = {
            archive_name,
            Path(archive_name).stem,
        }
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".zip"):
            if archive_name.endswith(suffix):
                archive_names.add(archive_name[: -len(suffix)])

        return any(
            candidate == dir_name or candidate.startswith(dir_name)
            for candidate in archive_names
        )

    def _merge_path(self, source: Path, destination: Path) -> None:
        if source.is_symlink():
            destination.unlink(missing_ok=True)
            os.symlink(os.readlink(source), destination)
            return

        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                symlinks=True,
            )
            return

        shutil.copy2(source, destination)

    def _cleanup_download_files(
        self,
        *paths: Path,
    ) -> None:
        for path in paths:
            with suppress(FileNotFoundError):
                path.unlink(missing_ok=True)

    def _is_download_cancelled(self) -> bool:
        cancel_event = self._download_cancel_event
        return bool(cancel_event is not None and cancel_event.is_set())

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

        major = cuda_version.split(".", 1)[0]
        mapping = {
            "12": "12.4",
            "13": "13.1",
        }
        return mapping.get(major)

    def _build_filename(self) -> str:
        tag = self.release_tag

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
