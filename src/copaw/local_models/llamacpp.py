# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import tempfile
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from copaw.constant import DEFAULT_LOCAL_PROVIDER_DIR

from ..utils import system_info

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadProgress:
    downloaded_bytes: int
    total_bytes: Optional[int]
    percent: Optional[float]
    file_name: str
    url: str


class DownloadCancelled(Exception):
    pass


ProgressCallback = Callable[[DownloadProgress], None]


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
        self._server_process: asyncio.subprocess.Process | None = None
        self._server_log_task: asyncio.Task[None] | None = None
        self._server_port: int | None = None
        self._server_model_name: str | None = None

    # -----------------------------
    # Public APIs
    # -----------------------------
    @property
    def download_url(self) -> str:
        """Get the download URL for the current environment configuration."""
        filename = self._build_filename()
        return f"{self.base_url}/{self.release_tag}/{filename}"

    @property
    def executable(self) -> Path:
        """The expected path of the llama.cpp server executable after download
        and extraction."""
        return self.target_dir / "llama-server"

    def check_llamacpp_installation(self) -> bool:
        """Check if the llama.cpp server executable exists."""
        return self.executable.exists()

    async def download(
        self,
        dest: str | Path,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[Any] = None,
        chunk_size: int = 1024 * 1024,
        timeout: int = 30,
    ) -> Path:
        """
        Download the corresponding release package and extract it.

        Args:
          - dest:
              Destination directory for the extracted package.
              The directory will be created automatically if it does not
              exist.
          - on_progress:
              Progress callback, signature:
              on_progress(progress: DownloadProgress) -> None
          - cancel_token:
              Optional cancel token, supports any object implementing
              is_set() -> bool, e.g. threading.Event
          - chunk_size:
              Size of each read chunk
          - timeout:
              Network timeout in seconds

        Returns:
          - Path to the extraction directory

        Raises:
          - DownloadCancelled: Download cancelled by user
          - URLError / HTTPError: Network error
          - ValueError: dest is an existing file path instead of a
            directory
          - OSError: File write error
          - TypeError: cancel_token does not meet requirements
        """
        return await asyncio.to_thread(
            self._download_sync,
            dest,
            on_progress,
            cancel_token,
            chunk_size,
            timeout,
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

        resolved_model_path = self._resolve_model_file(model_path)
        if self._server_process and self._server_process.returncode is None:
            await self.shutdown_server()

        port = self._find_free_port()
        process = await asyncio.create_subprocess_exec(
            str(self.executable),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--model",
            str(resolved_model_path),
            "--alias",
            model_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        self._server_process = process
        self._server_port = port
        self._server_model_name = model_name
        self._server_log_task = asyncio.create_task(
            self._drain_server_logs(),
            name="llamacpp_server_logs",
        )

        try:
            await self._wait_for_server_ready(port)
        except Exception:
            await self.shutdown_server()
            raise

        logger.info(
            "llama.cpp server started on port %s for model %s",
            port,
            model_name,
        )
        return port

    async def shutdown_server(self) -> None:
        """Shutdown the llama.cpp server if it's running."""
        if self._server_log_task and not self._server_log_task.done():
            self._server_log_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._server_log_task

        if self._server_process and self._server_process.returncode is None:
            self._server_process.terminate()
            try:
                await asyncio.wait_for(self._server_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._server_process.kill()
                await self._server_process.wait()

        self._server_process = None
        self._server_log_task = None
        self._server_port = None
        self._server_model_name = None

    def _download_sync(
        self,
        dest: str | Path,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[Any] = None,
        chunk_size: int = 1024 * 1024,
        timeout: int = 30,
    ) -> Path:
        """Perform the blocking download and extraction workflow."""
        self._validate_cancel_token(cancel_token)

        dest_dir = self._resolve_dest_dir(dest)
        url = self.download_url
        file_name = url.rsplit("/", 1)[-1]
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_path = dest_dir / file_name

        temp_path = final_path.with_name(final_path.name + ".part")

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "llama-release-downloader/1.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                total_bytes = response.headers.get("Content-Length")
                total_bytes_int = (
                    int(total_bytes)
                    if total_bytes and total_bytes.isdigit()
                    else None
                )

                downloaded = 0
                last_percent_int = -1

                with open(temp_path, "wb") as f:
                    while True:
                        if self._is_cancelled(cancel_token):
                            raise DownloadCancelled(
                                "Download cancelled by user.",
                            )

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)

                        if on_progress:
                            percent = None
                            if total_bytes_int and total_bytes_int > 0:
                                percent = downloaded * 100.0 / total_bytes_int
                                current_percent_int = int(percent)
                                if current_percent_int == last_percent_int:
                                    continue
                                last_percent_int = current_percent_int

                            on_progress(
                                DownloadProgress(
                                    downloaded_bytes=downloaded,
                                    total_bytes=total_bytes_int,
                                    percent=percent,
                                    file_name=file_name,
                                    url=url,
                                ),
                            )

                shutil.move(str(temp_path), str(final_path))
                if self._is_cancelled(cancel_token):
                    raise DownloadCancelled("Download cancelled by user.")

                self._extract_archive(final_path, dest_dir)
                final_path.unlink(missing_ok=True)

                if on_progress:
                    on_progress(
                        DownloadProgress(
                            downloaded_bytes=downloaded,
                            total_bytes=total_bytes_int,
                            percent=100.0 if total_bytes_int else None,
                            file_name=file_name,
                            url=url,
                        ),
                    )

                return dest_dir

        except DownloadCancelled:
            self._cleanup_download_files(temp_path, final_path)
            raise
        except Exception:
            self._cleanup_download_files(temp_path, final_path)
            raise

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

    @staticmethod
    def _find_free_port(host: str = "127.0.0.1") -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    async def _wait_for_server_ready(
        self,
        port: int,
        timeout_sec: float = 60.0,
    ) -> None:
        if not self._server_process:
            raise RuntimeError("llama.cpp server process was not created")

        deadline = asyncio.get_running_loop().time() + timeout_sec
        async with httpx.AsyncClient(timeout=2.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._server_process.returncode is not None:
                    raise RuntimeError(
                        "llama.cpp server exited before becoming ready",
                    )

                for endpoint in ("/health", "/v1/models"):
                    try:
                        response = await client.get(
                            f"http://127.0.0.1:{port}{endpoint}",
                        )
                    except httpx.HTTPError:
                        continue
                    if response.status_code < 500:
                        return

                await asyncio.sleep(0.5)

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

    def _extract_archive(self, archive_path: Path, dest_dir: Path) -> None:
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
                archive_path,
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _merge_extracted_content(
        self,
        staging_dir: Path,
        dest_dir: Path,
        archive_path: Path,
    ) -> None:
        extracted_entries = list(staging_dir.iterdir())
        source_root = staging_dir
        if (
            len(extracted_entries) == 1
            and extracted_entries[0].is_dir()
            and self._should_flatten_archive_root(
                extracted_entries[0],
                archive_path,
            )
        ):
            source_root = extracted_entries[0]

        for item in source_root.iterdir():
            self._merge_path(item, dest_dir / item.name)

    @staticmethod
    def _should_flatten_archive_root(
        root_dir: Path,
        archive_path: Path,
    ) -> bool:
        dir_name = root_dir.name
        archive_names = {
            archive_path.name,
            archive_path.stem,
        }
        for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".zip"):
            if archive_path.name.endswith(suffix):
                archive_names.add(archive_path.name[: -len(suffix)])

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
        temp_path: Path,
        archive_path: Path,
    ) -> None:
        with suppress(FileNotFoundError):
            temp_path.unlink(missing_ok=True)
        with suppress(FileNotFoundError):
            archive_path.unlink(missing_ok=True)

    def _validate_cancel_token(self, cancel_token: Optional[Any]) -> None:
        if cancel_token is None:
            return

        is_set = getattr(cancel_token, "is_set", None)
        if not callable(is_set):
            raise TypeError(
                "cancel_token must implement is_set() -> bool, "
                "e.g. threading.Event",
            )

    def _is_cancelled(self, cancel_token: Optional[Any]) -> bool:
        if cancel_token is None:
            return False
        return bool(cancel_token.is_set())

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
