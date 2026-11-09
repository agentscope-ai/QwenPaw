# -*- coding: utf-8 -*-
"""Managed MLX inference engine for Apple Silicon.

MLX runs as an isolated ``mlx-lm`` OpenAI-compatible server.  The runtime
lives in its own virtual environment so upgrading it never mutates the
Python environment that QwenPaw itself runs in.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from qwenpaw.constant import DEFAULT_LOCAL_PROVIDER_DIR
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.utils import system_info
from qwenpaw.utils.command_runner import (
    ManagedProcess,
    shutdown_process,
    shutdown_process_sync,
    start_command_async,
)

from .download_manager import (
    DownloadProgressTracker,
    DownloadTaskResult,
    DownloadTaskStatus,
)

logger = logging.getLogger(__name__)

MLX_LM_VERSION = "0.32.2"
_MLX_INSTALL_PACKAGE = f"mlx-lm=={MLX_LM_VERSION}"
_MLX_MARKER = ".qwenpaw-mlx-lm-version"
_MIN_MACOS_VERSION = (14, 0)


class MlxServerSetupResult(BaseModel):
    """Runtime information for a started MLX server."""

    port: int
    model_info: ModelInfo


class MlxBackend:
    """Install and supervise an MLX OpenAI-compatible server."""

    def __init__(self) -> None:
        self.target_dir = DEFAULT_LOCAL_PROVIDER_DIR / "mlx"
        self.venv_dir = self.target_dir / "venv"
        self.log_dir = self.target_dir / "logs"
        self._progress = DownloadProgressTracker()
        self._server_process: ManagedProcess | None = None
        self._server_port: int | None = None
        self._server_model_name: str | None = None
        self._server_transitioning = False
        self._install_task: asyncio.Task[None] | None = None
        self._install_process: asyncio.subprocess.Process | None = None
        self._cancel_requested = False
        self._device_name: str | None = None

    # -----------------------------
    # Capability / status
    # -----------------------------
    @property
    def venv_python(self) -> Path:
        """Path to the interpreter inside the managed MLX environment."""
        if self.os_name == "windows":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    @property
    def os_name(self) -> str:
        return system_info.get_os_name()

    @property
    def arch(self) -> str:
        return system_info.get_architecture()

    def check_installation(self) -> tuple[bool, str]:
        """Return whether the MLX runtime is installed."""
        marker = self.venv_dir / _MLX_MARKER
        if not self.venv_python.is_file():
            return False, "MLX runtime is not installed"
        try:
            version = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return False, "MLX runtime is not installed"
        if version != MLX_LM_VERSION:
            return False, "MLX runtime needs to be updated"
        return True, ""

    def check_installability(self) -> tuple[bool, str]:
        """Return whether this machine can run the MLX engine."""
        if self.os_name != "macos" or self.arch != "arm64":
            return (
                False,
                "MLX requires Apple Silicon (macOS on arm64).",
            )
        version = system_info.get_macos_version()
        if version is not None and version < _MIN_MACOS_VERSION:
            return (
                False,
                "MLX requires macOS 14 or newer.",
            )
        return True, ""

    def get_server_status(self) -> dict[str, Any]:
        """Return the current MLX server status snapshot."""
        process = self._server_process
        running = bool(process is not None and process.returncode is None)
        return {
            "running": running,
            "port": self._server_port,
            "model_name": self._server_model_name,
            "pid": process.pid if running and process is not None else None,
        }

    def is_server_transitioning(self) -> bool:
        """Return whether the MLX server is starting or stopping."""
        return self._server_transitioning

    def get_download_progress(self) -> dict[str, Any]:
        """Return the MLX runtime install progress snapshot."""
        return self._progress.snapshot()

    def is_download_active(self) -> bool:
        """Return whether the MLX runtime install is still running."""
        return self._progress.get_status() in {
            DownloadTaskStatus.PENDING,
            DownloadTaskStatus.DOWNLOADING,
            DownloadTaskStatus.CANCELING,
        }

    async def get_version(self) -> str:
        """Return the installed ``mlx-lm`` version."""
        installed, message = self.check_installation()
        if not installed:
            raise RuntimeError(message or "MLX runtime is not installed")
        return self._installed_version()

    async def get_accelerator_info(self) -> dict[str, str | None]:
        """Return the accelerator backing the MLX engine."""
        if self.check_installability()[0]:
            return {
                "accelerator": "metal",
                "device_name": await asyncio.to_thread(
                    self._resolve_device_name,
                ),
            }
        return {"accelerator": "cpu", "device_name": None}

    def _installed_version(self) -> str:
        """Read the version recorded after a successful install."""
        return (
            (self.venv_dir / _MLX_MARKER).read_text(encoding="utf-8").strip()
        )

    def _resolve_device_name(self) -> str | None:
        """Read the Apple Silicon chip name once."""
        if self._device_name is not None:
            return self._device_name
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
            name = result.stdout.strip()
            if name:
                self._device_name = name
        except (OSError, subprocess.SubprocessError):
            self._device_name = None
        return self._device_name

    # -----------------------------
    # Runtime install
    # -----------------------------
    def start_download(self) -> None:
        """Start installing the managed MLX runtime in the background."""
        installable, message = self.check_installability()
        if not installable:
            raise RuntimeError(message)
        if self.is_download_active():
            raise RuntimeError(
                "An MLX runtime install is already in progress.",
            )
        if self._install_task is not None and not self._install_task.done():
            raise RuntimeError(
                "An MLX runtime install is already in progress.",
            )

        self._cancel_requested = False
        self._progress.begin(
            total_bytes=None,
            model_name=_MLX_INSTALL_PACKAGE,
            source="pypi",
        )
        self._install_task = asyncio.create_task(
            self._install_runtime(),
            name="qwenpaw-mlx-runtime-install",
        )

    def cancel_download(self) -> None:
        """Request cancellation of the MLX runtime install."""
        self._cancel_requested = True
        self._progress.request_cancel()
        process = self._install_process
        if process is not None and process.returncode is None:
            process.terminate()

    async def _install_runtime(self) -> None:
        """Create the venv and install ``mlx-lm`` into it."""
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / "mlx-install.log"
            base_python = self._base_python()

            if self.venv_python.is_file():
                # Recreate a stale or partially removed environment.
                import shutil

                shutil.rmtree(self.venv_dir, ignore_errors=True)

            await self._run_install_command(
                [str(base_python), "-m", "venv", str(self.venv_dir)],
                log_path,
            )
            if self._cancel_requested:
                raise asyncio.CancelledError

            await self._run_install_command(
                [
                    str(self.venv_python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    _MLX_INSTALL_PACKAGE,
                ],
                log_path,
            )
            if self._cancel_requested:
                raise asyncio.CancelledError

            await self._run_install_command(
                [str(self.venv_python), "-c", "import mlx_lm"],
                log_path,
            )
            if self._cancel_requested:
                raise asyncio.CancelledError

            (self.venv_dir / _MLX_MARKER).write_text(
                MLX_LM_VERSION,
                encoding="utf-8",
            )
            self._progress.apply_result(
                DownloadTaskResult(
                    status=DownloadTaskStatus.COMPLETED,
                    local_path=str(self.venv_dir),
                ),
            )
            logger.info("MLX runtime installed at %s", self.venv_dir)
        except asyncio.CancelledError:
            self._progress.apply_result(
                DownloadTaskResult(status=DownloadTaskStatus.CANCELLED),
            )
            logger.info("MLX runtime install cancelled")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("MLX runtime install failed: %s", exc)
            self._progress.apply_result(
                DownloadTaskResult(
                    status=DownloadTaskStatus.FAILED,
                    error=f"MLX runtime install failed: {exc}",
                ),
            )
        finally:
            self._install_process = None

    async def _run_install_command(
        self,
        command: list[str],
        log_path: Path,
    ) -> None:
        """Run one install step and stream its output to the install log."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log_file:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._install_process = process
            returncode = await process.wait()
        if self._cancel_requested:
            raise asyncio.CancelledError
        if returncode != 0:
            raise RuntimeError(
                f"command failed with exit code {returncode}: "
                + " ".join(command),
            )

    def _base_python(self) -> Path:
        """Return the interpreter used to create the MLX environment."""
        runtime = (os.environ.get("QWENPAW_DESKTOP_PY_RUNTIME") or "").strip()
        if runtime and Path(runtime).is_file():
            return Path(runtime)
        if not getattr(sys, "frozen", False):
            return Path(sys.executable)
        executable = Path(sys.executable).resolve()
        candidate = (
            executable.parent.parent / "python-runtime/python/bin/python3"
        )
        if candidate.is_file():
            return candidate
        raise RuntimeError(
            "The bundled Python runtime is unavailable, so the MLX engine "
            "cannot be installed.",
        )

    # -----------------------------
    # Server lifecycle
    # -----------------------------
    async def setup_server(
        self,
        model_path: Path,
        model_name: str,
        max_context_length: int | None = None,
        port: int | None = None,
    ) -> MlxServerSetupResult:
        """Start the MLX server for a downloaded model directory."""
        if self.is_download_active():
            raise RuntimeError(
                "Wait for the MLX runtime install to finish before starting "
                "a model.",
            )
        installed, message = self.check_installation()
        if not installed:
            raise RuntimeError(message or "MLX runtime is not installed")
        if not model_path.exists():
            raise FileNotFoundError(f"Model path not found: {model_path}")

        resolved_dir = self._resolve_model_dir(model_path)
        model_info = self._build_model_info(
            model_name=model_name,
            model_path=resolved_dir,
        )

        if (
            model_name == self._server_model_name
            and self._server_process is not None
            and self._server_process.returncode is None
            and (port is None or port == self._server_port)
        ):
            logger.info(
                "Requested MLX model %s is already served on port %s",
                model_name,
                self._server_port,
            )
            return MlxServerSetupResult(
                port=self._server_port,
                model_info=model_info,
            )

        if self._server_process and self._server_process.returncode is None:
            await self.shutdown_server()

        self._server_transitioning = True
        port = self._resolve_server_port(port)
        try:
            self._server_process = await self._create_server_process(
                model_dir=resolved_dir,
                port=port,
            )
            self._server_port = port
            self._server_model_name = model_name
            logger.info("Waiting for MLX server to become ready...")
            await self.server_ready()
            logger.info("MLX server is ready on port %s", port)
        except Exception:
            await self.shutdown_server()
            raise
        finally:
            self._server_transitioning = False

        return MlxServerSetupResult(port=port, model_info=model_info)

    async def _create_server_process(
        self,
        *,
        model_dir: Path,
        port: int,
    ) -> ManagedProcess:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.venv_python),
            "-m",
            "mlx_lm",
            "server",
            "--model",
            str(model_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "INFO",
        ]
        logger.info(
            "Start MLX server with command:\n  > %s",
            " ".join(command),
        )
        process_kwargs: dict[str, Any] = {}
        if self.os_name != "windows":
            process_kwargs["start_new_session"] = True
        log_path = self.log_dir / "mlx-server.log"
        with open(log_path, "ab") as log_file:
            return await start_command_async(
                command,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                **process_kwargs,
            )

    async def server_ready(self, timeout: float = 180.0) -> bool:
        """Wait until the MLX OpenAI-compatible endpoint responds."""
        if not self._server_process or self._server_port is None:
            raise RuntimeError("MLX server process was not created")

        url = f"http://127.0.0.1:{self._server_port}/v1/models"
        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._server_process.returncode is not None:
                    raise RuntimeError(
                        "MLX server exited before becoming ready",
                    )
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return True
                except httpx.HTTPError as exc:
                    logger.debug("MLX health check failed: %s", exc)
                await asyncio.sleep(1)
        raise RuntimeError("Timed out waiting for MLX server to start")

    async def shutdown_server(self) -> None:
        """Stop the MLX server if it is running."""
        process = self._server_process
        self._server_process = None
        self._server_port = None
        self._server_model_name = None
        if process is not None and process.returncode is None:
            await shutdown_process(
                process,
                graceful_timeout=5.0,
                kill_timeout=3.0,
            )

    def shutdown_server_sync(self) -> None:
        """Best-effort synchronous cleanup for shutdown paths."""
        process = self._server_process
        self._server_process = None
        self._server_port = None
        self._server_model_name = None
        if process is not None and process.returncode is None:
            shutdown_process_sync(
                process,
                graceful_timeout=5.0,
                kill_timeout=1.0,
            )

    def shutdown_install_sync(self) -> None:
        """Terminate a runtime install during application shutdown."""
        self._cancel_requested = True
        process = self._install_process
        if process is not None and process.returncode is None:
            process.terminate()

    # -----------------------------
    # Internal helpers
    # -----------------------------
    @staticmethod
    def _resolve_model_dir(model_path: Path) -> Path:
        path = model_path.expanduser()
        if path.is_file():
            path = path.parent
        resolved = path.resolve()
        if not (resolved / "config.json").is_file():
            raise RuntimeError(
                "MLX models must be directories containing config.json and "
                "safetensors weights: "
                f"{resolved}",
            )
        if not any(resolved.glob("*.safetensors")):
            raise RuntimeError(
                f"MLX model at {resolved} does not contain safetensors "
                "weights.",
            )
        return resolved

    @staticmethod
    def _build_model_info(
        model_name: str,
        model_path: Path,
    ) -> ModelInfo:
        return ModelInfo(
            id=str(model_path),
            name=model_name,
            model_type="chat",
            supports_multimodal=False,
            supports_image=False,
            supports_video=False,
            probe_source="probed",
        )

    @staticmethod
    def _find_free_port(host: str = "127.0.0.1") -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    @staticmethod
    def _is_port_available(port: int, host: str = "127.0.0.1") -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if system_info.get_os_name() == "windows" and hasattr(
                socket,
                "SO_EXCLUSIVEADDRUSE",
            ):
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_EXCLUSIVEADDRUSE,
                    1,
                )
            try:
                sock.bind((host, port))
            except OSError:
                return False
        return True

    def _resolve_server_port(self, requested_port: int | None) -> int:
        if requested_port is None:
            return self._find_free_port()
        if not self._is_port_available(requested_port):
            raise ValueError(
                f"Requested MLX port is unavailable: {requested_port}",
            )
        return requested_port
