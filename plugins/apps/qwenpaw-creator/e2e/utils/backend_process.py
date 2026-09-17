# -*- coding: utf-8 -*-
# pylint: disable=consider-using-with
"""Launch and hard-restart the real Creator backend as an external process.

The release E2E suite deliberately imports no backend module here.  Recovery
is exercised through the same uvicorn entry point and public HTTP surface used
by the local product runtime.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import requests


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class ExternalCreatorBackend:
    """A restartable uvicorn child backed by one durable CREATOR_DATA_ROOT."""

    def __init__(
        self,
        *,
        backend_dir: Path,
        data_root: Path,
        log_path: Path,
        providers_enabled: bool = False,
        entrypoint: Path | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self.backend_dir = backend_dir.resolve()
        self.data_root = data_root.resolve()
        self.log_path = log_path.resolve()
        self.providers_enabled = providers_enabled
        self.entrypoint = (
            entrypoint.resolve() if entrypoint is not None else None
        )
        self.extra_env = dict(extra_env or {})
        self.port = reserve_loopback_port()
        self.process: subprocess.Popen[bytes] | None = None
        self._log_handle = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def health_url(self) -> str:
        return f"{self.origin}/api/qwenpaw-creator/health"

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "CREATOR_DATA_ROOT": str(self.data_root),
                "CREATOR_MODEL_CONFIG_PATH": str(
                    self.data_root / "config" / "model_config.json",
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        if not self.providers_enabled:
            # Deterministic recovery lanes must never spend provider quota.
            # Empty process-level values take precedence over project .env.
            env.update(
                {
                    "TEXT_API_KEY": "",
                    "VLM_API_KEY": "",
                    "DASHSCOPE_API_KEY": "",
                    "IMAGE_API_KEY": "",
                    "DASHSCOPE_IMAGE_API_KEY": "",
                    "OPENAI_IMAGE_API_KEY": "",
                    "VIDEO_API_KEY": "",
                    "OSS_API_KEY": "",
                    "OSS_ACCESS_KEY_ID": "",
                    "OSS_ACCESS_KEY_SECRET": "",
                },
            )
        env.update(self.extra_env)
        return env

    def start(self, *, timeout: float = 120) -> None:
        if self.process is not None:
            raise AssertionError("Creator backend process is already running")
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("ab")
        if self.entrypoint is None:
            command = [sys.executable, "-m", "uvicorn", "dev_main:app"]
        else:
            command = [sys.executable, str(self.entrypoint)]
        command.extend(
            [
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
        )
        self.process = subprocess.Popen(
            command,
            cwd=self.backend_dir,
            env=self._environment(),
            stdin=subprocess.DEVNULL,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    "Creator backend exited during startup:\n"
                    + self.log_tail(),
                )
            try:
                response = requests.get(self.health_url, timeout=1)
                payload = response.json()
                if (
                    response.status_code == 200
                    and payload.get("status") == "ok"
                    and (payload.get("runtime") == "creator-filesystem")
                ):
                    return
            except (requests.RequestException, ValueError):
                pass
            time.sleep(0.1)
        raise AssertionError(
            "Creator backend did not become healthy:\n" + self.log_tail(),
        )

    def crash(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        self._close_process_handles()

    def stop(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        self._close_process_handles()

    def _close_process_handles(self) -> None:
        self.process = None
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def log_tail(self, *, lines: int = 80) -> str:
        if self._log_handle is not None:
            self._log_handle.flush()
        if not self.log_path.exists():
            return "<no backend log>"
        return "\n".join(
            self.log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()[-lines:],
        )
