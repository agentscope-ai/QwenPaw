# -*- coding: utf-8 -*-
"""Windows AppContainer isolation for long-running Hub runtimes."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from ..sandbox.config import MountSpec, SandboxConfig, SandboxMode
from ..sandbox.windows_appcontainer_sandbox import (
    WindowsAppContainerProcess,
    WindowsAppContainerSandbox,
)
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

_BROKER_START_TIMEOUT_SECONDS = 5.0
_PROBE_TIMEOUT_SECONDS = 10.0


@dataclass
class _WindowsRuntimeBoundary:
    sandbox: WindowsAppContainerSandbox
    loopback_broker: subprocess.Popen[bytes]


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
                "privileges for AppContainer ACLs and inbound loopback.",
            )
        runtime_root = _runtime_root(record)
        self.release(record.runtime_id)
        mounts = [
            MountSpec(str(path), writable=False) for path in _read_roots()
        ]
        mounts.extend(
            [
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
        broker: subprocess.Popen[bytes] | None = None
        try:
            asyncio.run(sandbox.__aenter__())
            broker = self._start_loopback_broker(sandbox.container_name)
            boundary = _WindowsRuntimeBoundary(sandbox, broker)
            with self._lock:
                self._boundaries[record.runtime_id] = boundary
            self._probe(record, runtime_root, sandbox)
        except Exception as exc:
            if broker is not None:
                self._stop_broker(broker)
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
        if boundary.loopback_broker.poll() is not None:
            raise ProcessIsolationError(
                "Windows inbound loopback broker exited before launch.",
            )
        return boundary.sandbox.spawn_process(
            launch.command,
            cwd=str(record.working_dir),
            env=launch.environment,
            log_handle=log_handle,
        )

    def release(self, runtime_id: str) -> None:
        """Stop the loopback broker and release retained process handles."""
        with self._lock:
            boundary = self._boundaries.pop(runtime_id, None)
        if boundary is None:
            return
        asyncio.run(boundary.sandbox.stop())
        self._stop_broker(boundary.loopback_broker)

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

    def _start_loopback_broker(
        self,
        container_name: str,
    ) -> subprocess.Popen[bytes]:
        command = [
            self._checknetisolation_path(),
            "LoopbackExempt",
            "-is",
            f"-n={container_name}",
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # pylint: disable-next=consider-using-with
        broker = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        time.sleep(min(0.25, _BROKER_START_TIMEOUT_SECONDS))
        if broker.poll() is not None:
            raise ProcessIsolationError(
                "Windows inbound loopback broker exited with code "
                f"{broker.returncode}.",
            )
        return broker

    @staticmethod
    def _stop_broker(broker: subprocess.Popen[bytes]) -> None:
        if broker.poll() is not None:
            return
        broker.terminate()
        try:
            broker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            broker.kill()
            broker.wait(timeout=5)

    def _probe(
        self,
        record: RuntimeRecord,
        runtime_root: Path,
        sandbox: WindowsAppContainerSandbox,
    ) -> None:
        self._probe_filesystem(record, runtime_root, sandbox)
        self._probe_outbound_loopback(record, sandbox)
        self._probe_inbound_loopback(record, sandbox)

    @staticmethod
    def _run_probe(
        sandbox: WindowsAppContainerSandbox,
        record: RuntimeRecord,
        script: str,
    ) -> None:
        probe_log = record.log_file.parent / ".windows-boundary-probe.log"
        with probe_log.open("a", encoding="utf-8") as log_handle:
            process = sandbox.spawn_process(
                [sys.executable, "-B", "-c", script],
                cwd=str(record.working_dir),
                env=dict(os.environ),
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
    ) -> None:
        allowed = record.working_dir / ".isolation-probe"
        forbidden = runtime_root.parent / (
            f"qwenpaw-hub-forbidden-{os.getpid()}"
        )
        written = record.working_dir / ".isolation-written"
        allowed.write_text("allowed", encoding="utf-8")
        forbidden.write_text("forbidden", encoding="utf-8")
        script = (
            "from pathlib import Path\n"
            f"allowed = Path({str(allowed)!r})\n"
            f"forbidden = Path({str(forbidden)!r})\n"
            f"written = Path({str(written)!r})\n"
            "assert allowed.read_text(encoding='utf-8') == 'allowed'\n"
            "written.write_text('ok', encoding='utf-8')\n"
            "try:\n"
            "    forbidden.read_bytes()\n"
            "except (FileNotFoundError, PermissionError):\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('forbidden path is readable')\n"
        )
        try:
            self._run_probe(sandbox, record, script)
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

    def _probe_outbound_loopback(
        self,
        record: RuntimeRecord,
        sandbox: WindowsAppContainerSandbox,
    ) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = int(listener.getsockname()[1])
            script = (
                "import socket; "
                "client=socket.socket(); client.settimeout(1); "
                f"code=client.connect_ex(('127.0.0.1',{port})); "
                "client.close(); raise SystemExit(41 if code == 0 else 0)"
            )
            self._run_probe(sandbox, record, script)

    def _probe_inbound_loopback(
        self,
        record: RuntimeRecord,
        sandbox: WindowsAppContainerSandbox,
    ) -> None:
        script = (
            "import socket; "
            "server=socket.socket(); "
            "server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); "
            f"server.bind(('127.0.0.1',{record.port})); "
            "server.listen(1); connection,_=server.accept(); "
            "connection.sendall(b'ok'); connection.close(); server.close()"
        )
        command = [sys.executable, "-B", "-c", script]
        probe_log = record.log_file.parent / ".windows-network-probe.log"
        with probe_log.open("a", encoding="utf-8") as log_handle:
            process = sandbox.spawn_process(
                command,
                cwd=str(record.working_dir),
                env=dict(os.environ),
                log_handle=log_handle,
            )
            try:
                self._connect_to_probe(record.port, process)
                if process.wait(timeout=5) != 0:
                    raise ProcessIsolationError(
                        "Windows inbound loopback probe exited "
                        "unsuccessfully.",
                    )
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
        probe_log.unlink(missing_ok=True)

    @staticmethod
    def _connect_to_probe(
        port: int,
        process: WindowsAppContainerProcess,
    ) -> None:
        deadline = time.monotonic() + _PROBE_TIMEOUT_SECONDS
        last_error = "runtime listener was not reachable"
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                raise ProcessIsolationError(
                    "Windows inbound loopback probe exited with code "
                    f"{exit_code}.",
                )
            try:
                with socket.create_connection(
                    ("127.0.0.1", port),
                    timeout=0.5,
                ) as client:
                    if client.recv(2) == b"ok":
                        return
            except OSError as exc:
                last_error = str(exc)
            time.sleep(0.05)
        raise ProcessIsolationError(
            f"Windows inbound loopback probe failed: {last_error}",
        )
