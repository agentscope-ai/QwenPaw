# -*- coding: utf-8 -*-
"""Fail-closed isolated local process driver for QwenPaw Pro."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import IO, Any

from .driver import RuntimeDriver
from .models import RuntimeRecord, RuntimeState
from .process_isolation import ProcessIsolator, platform_process_isolator

_START_TIMEOUT_SECONDS = 30.0
_STOP_TIMEOUT_SECONDS = 10.0


def allocate_loopback_port() -> int:
    """Ask the OS for an unused loopback TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


class LocalProcessRuntimeDriver(RuntimeDriver):
    """Run a complete QwenPaw process tree inside an OS sandbox."""

    name = "local"
    security_level = "isolated-local-required"

    def __init__(
        self,
        *,
        start_timeout: float = _START_TIMEOUT_SECONDS,
        stop_timeout: float = _STOP_TIMEOUT_SECONDS,
        isolator: ProcessIsolator | None = None,
    ) -> None:
        self._start_timeout = start_timeout
        self._stop_timeout = stop_timeout
        self._isolator = isolator or platform_process_isolator()
        if self._isolator.name == "macos-seatbelt":
            self.security_level = "isolated-local"
        elif self._isolator.name == "linux-bubblewrap":
            self.security_level = "isolated-local-shared-network"
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._log_handles: dict[str, IO[str]] = {}

    def start(
        self,
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> RuntimeRecord:
        """Start an isolated local QwenPaw process and wait for readiness."""
        if not credentials.get("QWENPAW_PRO_INTERNAL_TOKEN"):
            raise RuntimeError(
                "Managed local runtime requires an internal boundary token.",
            )
        current = self._processes.get(record.runtime_id)
        if current is not None and current.poll() is None:
            return replace(
                record,
                state=RuntimeState.RUNNING,
                pid=current.pid,
                last_error=None,
            )

        port = record.port or allocate_loopback_port()
        for path in (
            record.working_dir,
            record.working_dir / "tmp",
            record.secret_dir,
            record.backup_dir,
            record.log_file.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

        log_handle = record.log_file.open(
            "a",
            encoding="utf-8",
            buffering=1,
        )
        command = [
            sys.executable,
            "-m",
            "qwenpaw",
            "app",
            "--host",
            record.host,
            "--port",
            str(port),
        ]
        launch_record = replace(record, port=port)
        environment = self.runtime_environment(launch_record, credentials)
        isolated = self._isolator.prepare(
            launch_record,
            command,
            environment,
        )
        popen_options: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_options[
                "creationflags"
            ] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True

        try:
            # The process remains owned by this driver until stop or close.
            # pylint: disable-next=consider-using-with
            process = subprocess.Popen(
                isolated.command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=isolated.environment,
                cwd=record.working_dir,
                **popen_options,
            )
        except Exception:
            log_handle.close()
            raise

        self._processes[record.runtime_id] = process
        self._log_handles[record.runtime_id] = log_handle
        starting = replace(
            launch_record,
            state=RuntimeState.STARTING,
            pid=process.pid,
            last_error=None,
        )
        try:
            self._wait_until_ready(
                starting,
                process,
                isolated.environment.get(
                    "QWENPAW_PRO_INTERNAL_TOKEN",
                    "",
                ),
            )
        except Exception as exc:
            self._terminate(record.runtime_id, process)
            raise RuntimeError(
                f"Runtime {record.runtime_id} failed to start: {exc}",
            ) from exc
        return replace(starting, state=RuntimeState.RUNNING)

    def stop(self, record: RuntimeRecord) -> RuntimeRecord:
        """Stop a child owned by this driver.

        Persisted process identifiers are deliberately not trusted.
        """
        process = self._processes.get(record.runtime_id)
        if process is not None and process.poll() is None:
            self._terminate(record.runtime_id, process)
        else:
            self._close_log(record.runtime_id)
        return replace(
            record,
            state=RuntimeState.STOPPED,
            pid=None,
            last_error=None,
        )

    def status(self, record: RuntimeRecord) -> RuntimeRecord:
        """Observe a process created during this supervisor lifetime."""
        process = self._processes.get(record.runtime_id)
        if process is None:
            if record.state in {RuntimeState.RUNNING, RuntimeState.STARTING}:
                return replace(
                    record,
                    state=RuntimeState.STOPPED,
                    pid=None,
                    last_error=(
                        "Runtime process is not owned by this supervisor."
                    ),
                )
            return record
        exit_code = process.poll()
        if exit_code is None:
            return replace(
                record,
                state=RuntimeState.RUNNING,
                pid=process.pid,
                last_error=None,
            )
        self._processes.pop(record.runtime_id, None)
        self._close_log(record.runtime_id)
        return replace(
            record,
            state=RuntimeState.FAILED if exit_code else RuntimeState.STOPPED,
            pid=None,
            last_error=(
                f"Runtime process exited with code {exit_code}."
                if exit_code
                else None
            ),
        )

    def close(self) -> None:
        """Stop every child process created by this driver."""
        for runtime_id, process in list(self._processes.items()):
            if process.poll() is None:
                self._terminate(runtime_id, process)
            else:
                self._processes.pop(runtime_id, None)
                self._close_log(runtime_id)

    @staticmethod
    def runtime_environment(
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> dict[str, str]:
        inherited_names = {
            "PATH",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in inherited_names
        }
        python_path = environment.get("PYTHONPATH", "")
        if python_path:
            environment["PYTHONPATH"] = os.pathsep.join(
                str(Path(value).expanduser().resolve())
                for value in python_path.split(os.pathsep)
                if value
            )
        environment.update(credentials)
        environment["HOME"] = str(record.working_dir)
        environment["TMP"] = str(record.working_dir / "tmp")
        environment["TEMP"] = str(record.working_dir / "tmp")
        environment["TMPDIR"] = str(record.working_dir / "tmp")
        environment["QWENPAW_WORKING_DIR"] = str(record.working_dir)
        environment["QWENPAW_SECRET_DIR"] = str(record.secret_dir)
        environment["QWENPAW_BACKUP_DIR"] = str(record.backup_dir)
        environment[
            "QWENPAW_KEYRING_ACCOUNT"
        ] = f"qwenpaw-pro-{record.runtime_id}"
        environment["QWENPAW_PRO_RUNTIME_ID"] = record.runtime_id
        environment["QWENPAW_PRO_TENANT_ID"] = record.tenant_id
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment

    def _wait_until_ready(
        self,
        record: RuntimeRecord,
        process: subprocess.Popen[str],
        runtime_token: str,
    ) -> None:
        deadline = time.monotonic() + self._start_timeout
        url = f"http://{record.host}:{record.port}/api/healthz"
        last_error = "health endpoint was not reachable"
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeError(
                    f"process exited with code {exit_code}",
                )
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "X-QwenPaw-Pro-Runtime-Token": runtime_token,
                    },
                )
                with urllib.request.urlopen(request, timeout=1) as response:
                    if response.status == 200:
                        return
                    last_error = f"health endpoint returned {response.status}"
            except (OSError, urllib.error.URLError) as exc:
                last_error = str(exc)
            time.sleep(0.1)
        raise TimeoutError(last_error)

    def _terminate(
        self,
        runtime_id: str,
        process: subprocess.Popen[str],
    ) -> None:
        if sys.platform == "win32":
            process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=self._stop_timeout)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=self._stop_timeout)
        self._processes.pop(runtime_id, None)
        self._close_log(runtime_id)

    def _close_log(self, runtime_id: str) -> None:
        handle = self._log_handles.pop(runtime_id, None)
        if handle is not None:
            handle.close()
