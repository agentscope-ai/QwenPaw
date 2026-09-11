# -*- coding: utf-8 -*-
"""Windows AppContainer isolation for long-running Hub runtimes."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from ..sandbox.config import MountSpec, SandboxConfig, SandboxMode
from ..sandbox.windows_appcontainer_sandbox import WindowsAppContainerSandbox
from ..utils.platform import is_windows_admin
from .models import RuntimeRecord
from .process_isolation import (
    IsolatedLaunch,
    ManagedProcess,
    ProcessIsolationError,
    ProcessIsolator,
    _read_roots,
    _runtime_root,
)

_PROBE_TIMEOUT_SECONDS = 10.0


@dataclass
class _WindowsRuntimeBoundary:
    sandbox: WindowsAppContainerSandbox
    loopback_sid: str


class WindowsAppContainerIsolator(ProcessIsolator):
    """Run every Windows Local runtime in a dedicated AppContainer."""

    name = "windows-appcontainer"

    def __init__(self) -> None:
        self._boundaries: dict[str, _WindowsRuntimeBoundary] = {}
        self._lock = threading.RLock()

    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        """Create and probe a per-runtime AppContainer boundary."""
        if sys.platform != "win32":
            raise ProcessIsolationError(
                "Windows AppContainer isolation requires Windows.",
            )
        if not is_windows_admin():
            raise ProcessIsolationError(
                "Windows Local Hub runtimes require administrator "
                "privileges for AppContainer ACLs and loopback access.",
            )
        runtime_root = _runtime_root(record)
        self.release(record.runtime_id)
        mounts = [
            MountSpec(str(path), writable=False) for path in _read_roots()
        ]
        mounts.extend(
            [
                MountSpec(
                    str(record.working_dir / "tmp"),
                    writable=True,
                ),
                MountSpec(
                    str(record.working_dir / "appdata" / "roaming"),
                    writable=True,
                ),
                MountSpec(
                    str(record.working_dir / "appdata" / "local"),
                    writable=True,
                ),
                MountSpec(str(record.secret_dir), writable=True),
                MountSpec(str(record.backup_dir), writable=True),
                MountSpec(str(record.log_file.parent), writable=True),
            ],
        )
        sandbox = WindowsAppContainerSandbox(
            SandboxConfig(
                mode=SandboxMode.WINDOWS,
                workspace_dir=str(record.working_dir),
                mounts=mounts,
                allow_read_all=False,
                network_allow=["*"],
                timeout_seconds=int(_PROBE_TIMEOUT_SECONDS),
            ),
        )
        loopback_enabled = False
        try:
            asyncio.run(sandbox.__aenter__())
            self._set_loopback_exemption(sandbox.container_sid, enabled=True)
            loopback_enabled = True
            boundary = _WindowsRuntimeBoundary(
                sandbox,
                sandbox.container_sid,
            )
            with self._lock:
                self._boundaries[record.runtime_id] = boundary
            self._probe(
                record,
                runtime_root,
                sandbox,
                environment,
            )
        except Exception as exc:
            if loopback_enabled:
                self._set_loopback_exemption(
                    sandbox.container_sid,
                    enabled=False,
                    check=False,
                )
            asyncio.run(sandbox.stop())
            with self._lock:
                self._boundaries.pop(record.runtime_id, None)
            if isinstance(exc, ProcessIsolationError):
                raise
            raise ProcessIsolationError(
                f"Windows AppContainer isolation is unavailable: {exc}",
            ) from exc
        return IsolatedLaunch(list(command), dict(environment))

    def launch(
        self,
        record: RuntimeRecord,
        launch: IsolatedLaunch,
        log_handle: IO[str],
    ) -> ManagedProcess:
        """Start the runtime inside its initialized AppContainer."""
        with self._lock:
            boundary = self._boundaries.get(record.runtime_id)
        if boundary is None:
            raise ProcessIsolationError(
                f"Windows boundary is not prepared: {record.runtime_id}",
            )
        return boundary.sandbox.spawn_process(
            launch.command,
            cwd=str(record.working_dir),
            env=launch.environment,
            log_handle=log_handle,
        )

    def release(self, runtime_id: str) -> None:
        """Release retained process handles and the loopback exemption."""
        with self._lock:
            boundary = self._boundaries.pop(runtime_id, None)
        if boundary is None:
            return
        asyncio.run(boundary.sandbox.stop())
        self._set_loopback_exemption(
            boundary.loopback_sid,
            enabled=False,
            check=False,
        )

    @staticmethod
    def _checknetisolation_path() -> str:
        executable = shutil.which("CheckNetIsolation.exe")
        if executable:
            return executable
        system_root = os.environ.get("SystemRoot", "").strip()
        if system_root:
            candidate = (
                Path(system_root) / "System32" / "CheckNetIsolation.exe"
            )
            if candidate.is_file():
                return str(candidate)
        raise ProcessIsolationError(
            "CheckNetIsolation.exe is required for Windows Local runtimes.",
        )

    def _set_loopback_exemption(
        self,
        container_sid: str,
        *,
        enabled: bool,
        check: bool = True,
    ) -> None:
        command = [
            self._checknetisolation_path(),
            "LoopbackExempt",
            "-a" if enabled else "-d",
            f"-p={container_sid}",
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ProcessIsolationError(
                "Windows loopback exemption failed with code "
                f"{result.returncode}: {detail}",
            )

    def _probe(
        self,
        record: RuntimeRecord,
        runtime_root: Path,
        sandbox: WindowsAppContainerSandbox,
        environment: Mapping[str, str],
    ) -> None:
        self._probe_filesystem(
            record,
            runtime_root,
            sandbox,
            environment,
        )

    @staticmethod
    def _run_probe(
        sandbox: WindowsAppContainerSandbox,
        record: RuntimeRecord,
        script: str,
        environment: Mapping[str, str],
    ) -> None:
        probe_log = record.log_file.parent / ".windows-boundary-probe.log"
        with probe_log.open("a", encoding="utf-8") as log_handle:
            process = sandbox.spawn_process(
                [sys.executable, "-B", "-c", script],
                cwd=str(record.working_dir),
                env=dict(environment),
                log_handle=log_handle,
            )
            try:
                exit_code = process.wait(timeout=_PROBE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                process.terminate()
                process.wait(timeout=5)
                raise ProcessIsolationError(
                    "Windows AppContainer probe timed out.",
                ) from exc
        detail = probe_log.read_text(encoding="utf-8").strip()
        probe_log.unlink(missing_ok=True)
        if exit_code != 0:
            raise ProcessIsolationError(
                "Windows AppContainer probe failed with code "
                f"{exit_code}: {detail}",
            )

    def _probe_filesystem(
        self,
        record: RuntimeRecord,
        runtime_root: Path,
        sandbox: WindowsAppContainerSandbox,
        environment: Mapping[str, str],
    ) -> None:
        allowed = record.working_dir / ".isolation-probe"
        forbidden = runtime_root.parent / (
            f"qwenpaw-hub-forbidden-{os.getpid()}"
        )
        written = record.working_dir / ".isolation-written"
        staging = record.working_dir / "tmp" / ".isolation-staging"
        allowed.write_text("allowed", encoding="utf-8")
        forbidden.write_text("forbidden", encoding="utf-8")
        script = (
            "import shutil\n"
            "from pathlib import Path\n"
            f"allowed = Path({str(allowed)!r})\n"
            f"forbidden = Path({str(forbidden)!r})\n"
            f"written = Path({str(written)!r})\n"
            f"staging = Path({str(staging)!r})\n"
            "assert allowed.read_text(encoding='utf-8') == 'allowed'\n"
            "written.write_text('ok', encoding='utf-8')\n"
            "nested = staging / 'nested'\n"
            "nested.mkdir(parents=True)\n"
            "payload = nested / 'payload.txt'\n"
            "payload.write_text('nested', encoding='utf-8')\n"
            "assert payload.read_text(encoding='utf-8') == 'nested'\n"
            "shutil.rmtree(staging)\n"
            "assert not staging.exists()\n"
            "try:\n"
            "    forbidden.read_bytes()\n"
            "except (FileNotFoundError, PermissionError):\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('forbidden path is readable')\n"
        )
        try:
            self._run_probe(
                sandbox,
                record,
                script,
                environment,
            )
            if written.read_text(encoding="utf-8") != "ok":
                raise ProcessIsolationError(
                    "Windows AppContainer write probe failed.",
                )
            if not forbidden.is_file():
                raise ProcessIsolationError(
                    "Windows AppContainer modified the forbidden marker.",
                )
        finally:
            allowed.unlink(missing_ok=True)
            forbidden.unlink(missing_ok=True)
            written.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)
