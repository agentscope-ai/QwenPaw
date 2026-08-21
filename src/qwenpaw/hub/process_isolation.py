# -*- coding: utf-8 -*-
"""Fail-closed OS process isolation for local Hub runtimes."""

from __future__ import annotations

import mimetypes
import os
import shutil
import socket
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Mapping, Protocol, Sequence

from .models import RuntimeRecord


class ProcessIsolationError(RuntimeError):
    """Raised when the required local isolation boundary is unavailable."""


@dataclass(frozen=True)
class IsolatedLaunch:
    """Prepared process command and environment."""

    command: list[str]
    environment: dict[str, str]


class ManagedProcess(Protocol):
    """Process handle required by the local runtime supervisor."""

    pid: int

    def poll(self) -> int | None:
        """Return the exit code or None while the process is running."""

    def terminate(self) -> None:
        """Request termination of the complete managed process tree."""

    def kill(self) -> None:
        """Force termination of the complete managed process tree."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process exit and return its exit code."""


class ProcessIsolator(ABC):
    """Wrap a complete runtime process in a platform security boundary."""

    name: str

    @abstractmethod
    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        """Return a launch specification or fail closed."""

    def launch(
        self,
        record: RuntimeRecord,
        launch: IsolatedLaunch,
        log_handle: IO[str],
    ) -> ManagedProcess:
        """Start a prepared process inside the platform boundary."""
        options: dict[str, Any] = {}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        # pylint: disable-next=consider-using-with
        return subprocess.Popen(
            launch.command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=launch.environment,
            cwd=record.working_dir,
            **options,
        )

    def release(self, runtime_id: str) -> None:
        """Release platform resources retained for one runtime."""
        del runtime_id


def _runtime_root(record: RuntimeRecord) -> Path:
    roots = {
        record.working_dir.resolve().parent,
        record.secret_dir.resolve().parent,
        record.backup_dir.resolve().parent,
        record.log_file.resolve().parent.parent,
    }
    if len(roots) != 1:
        raise ProcessIsolationError(
            f"Runtime paths do not share one root: {record.runtime_id}",
        )
    return roots.pop()


def _read_roots() -> list[Path]:
    source_root = Path(__file__).resolve().parents[2]
    roots = {
        Path("/etc/ca-certificates").resolve(),
        Path("/etc/hosts").resolve(),
        Path("/etc/nsswitch.conf").resolve(),
        Path("/etc/resolv.conf"),
        Path("/etc/ssl/certs").resolve(),
        Path("/etc/pki/tls/certs").resolve(),
        Path(sys.base_prefix).resolve(),
        Path(sys.executable).resolve(),
        Path(sys.prefix).resolve(),
        source_root,
    }
    roots.update(Path(path).resolve() for path in mimetypes.knownfiles)
    if source_root.name == "src":
        repository_root = source_root.parent
        roots.add(repository_root / "packages" / "qwenpawmail-mcp" / "src")
        roots.add(repository_root / "website" / "public" / "docs")
        roots.add(repository_root / "console" / "dist")
    return sorted((path for path in roots if path.exists()), key=str)


class LinuxBubblewrapIsolator(ProcessIsolator):
    """Use Linux namespaces and an allowlisted filesystem view."""

    name = "linux-bubblewrap"

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or shutil.which("bwrap") or ""

    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        """Build a namespace-isolated bubblewrap invocation."""
        if not self._executable:
            raise ProcessIsolationError(
                "Local isolation requires bubblewrap (bwrap) on Linux.",
            )
        runtime_root = _runtime_root(record)
        args = [
            self._executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            "/",
        ]
        for path in (
            "/usr",
            "/bin",
            "/sbin",
            "/lib",
            "/lib64",
        ):
            if Path(path).exists():
                args.extend(["--ro-bind", path, path])
        for path in _read_roots():
            args.extend(["--ro-bind", str(path), str(path)])
        args.extend(
            [
                "--tmpfs",
                "/tmp",
                "--bind",
                str(runtime_root),
                str(runtime_root),
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--chdir",
                str(record.working_dir.resolve()),
                "--",
                *command,
            ],
        )
        self._probe(args, runtime_root, environment)
        return IsolatedLaunch(args, dict(environment))

    def _probe(
        self,
        runtime_args: Sequence[str],
        runtime_root: Path,
        environment: Mapping[str, str],
    ) -> None:
        probe_file = runtime_root / ".isolation-probe"
        probe_file.write_text("probe", encoding="utf-8")
        marker = runtime_root.parent / (f"qwenpaw-hub-forbidden-{os.getpid()}")
        marker.write_text("forbidden", encoding="utf-8")
        separator = runtime_args.index("--", 1)
        probe_args = [
            *runtime_args[: separator + 1],
            "/bin/sh",
            "-c",
            f'test -r "{probe_file}" && test ! -e "{marker}"',
        ]
        try:
            result = subprocess.run(
                probe_args,
                env=dict(environment),
                cwd=runtime_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        finally:
            probe_file.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
        if result.returncode != 0:
            detail = result.stderr.strip() or "isolation probe failed"
            raise ProcessIsolationError(
                f"bubblewrap isolation is unavailable: {detail}",
            )


class MacOSSeatbeltIsolator(ProcessIsolator):
    """Use a deny-default Seatbelt profile for the whole runtime tree."""

    name = "macos-seatbelt"

    def __init__(self, executable: str = "/usr/bin/sandbox-exec") -> None:
        self._executable = executable

    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        """Compile and validate a runtime-specific Seatbelt profile."""
        executable = Path(self._executable)
        if not executable.is_file():
            raise ProcessIsolationError(
                "Local isolation requires sandbox-exec on macOS.",
            )
        profile_path = record.secret_dir / "runtime.sb"
        profile = self._profile(record)
        profile_path.write_text(profile, encoding="utf-8")
        try:
            os.chmod(profile_path, 0o600)
        except OSError:
            pass
        self._probe(profile_path, record, environment)
        return IsolatedLaunch(
            [self._executable, "-f", str(profile_path), *command],
            dict(environment),
        )

    def _profile(
        self,
        record: RuntimeRecord,
    ) -> str:
        runtime_root = _runtime_root(record)
        read_paths = [
            Path("/System"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/Library"),
            Path("/private/var/db/timezone"),
            *_read_roots(),
            runtime_root,
        ]
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process-exec*)",
            "(allow process-fork)",
            "(allow signal (target same-sandbox))",
            "(allow process-info* (target same-sandbox))",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            "(allow network-outbound)",
            '(deny network-outbound (remote ip "localhost:*"))',
            ("(allow network-bind " f'(local ip "localhost:{record.port}"))'),
            (
                "(allow network-inbound "
                f'(local ip "localhost:{record.port}"))'
            ),
            "(allow file-read-metadata)",
            '(allow file-read-data (literal "/"))',
        ]
        available_paths = {path for path in read_paths if path.exists()}
        for path in sorted(available_paths, key=str):
            value = self._escape(path)
            lines.append(f'(allow file-read* (subpath "{value}"))')
        for path in ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"):
            lines.append(f'(allow file-read* (literal "{path}"))')
            lines.append(f'(allow file-write* (literal "{path}"))')
        root_value = self._escape(runtime_root)
        lines.append(f'(allow file-write* (subpath "{root_value}"))')
        return "\n".join(lines)

    def _probe(
        self,
        profile_path: Path,
        record: RuntimeRecord,
        environment: Mapping[str, str],
    ) -> None:
        allowed = record.working_dir / ".isolation-probe"
        forbidden = _runtime_root(record).parent / (
            f"qwenpaw-hub-forbidden-{os.getpid()}"
        )
        forbidden.write_text("forbidden", encoding="utf-8")
        command_prefix = [
            self._executable,
            "-f",
            str(profile_path),
            sys.executable,
            "-B",
            "-c",
        ]
        try:
            allowed_result = subprocess.run(
                [
                    *command_prefix,
                    f"open({str(allowed)!r}, 'w').close()",
                ],
                env=dict(environment),
                cwd=record.working_dir,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            forbidden_result = subprocess.run(
                [
                    *command_prefix,
                    f"open({str(forbidden)!r}, 'r').read()",
                ],
                env=dict(environment),
                cwd=record.working_dir,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        finally:
            allowed.unlink(missing_ok=True)
            forbidden.unlink(missing_ok=True)
        if allowed_result.returncode != 0:
            detail = allowed_result.stderr.strip() or "write probe failed"
            raise ProcessIsolationError(
                f"Seatbelt isolation is unavailable: {detail}",
            )
        if forbidden_result.returncode == 0:
            raise ProcessIsolationError(
                "Seatbelt isolation probe read a host file.",
            )
        self._probe_loopback_denied(
            profile_path,
            record,
            environment,
        )

    def _probe_loopback_denied(
        self,
        profile_path: Path,
        record: RuntimeRecord,
        environment: Mapping[str, str],
    ) -> None:
        """Verify the runtime cannot connect to another host-local port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = int(listener.getsockname()[1])
            probe = (
                "import socket;"
                "client=socket.socket();"
                f"result=client.connect_ex(('127.0.0.1',{port}));"
                "raise SystemExit(0 if result else 1)"
            )
            result = subprocess.run(
                [
                    self._executable,
                    "-f",
                    str(profile_path),
                    sys.executable,
                    "-B",
                    "-c",
                    probe,
                ],
                env=dict(environment),
                cwd=record.working_dir,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        if result.returncode != 0:
            raise ProcessIsolationError(
                "Seatbelt isolation probe reached another loopback port.",
            )

    @staticmethod
    def _escape(path: Path) -> str:
        value = str(path.resolve())
        if "\n" in value or "\r" in value:
            raise ProcessIsolationError("Seatbelt path contains a newline.")
        return value.replace("\\", "\\\\").replace('"', '\\"')


class UnsupportedProcessIsolator(ProcessIsolator):
    """Reject local runtimes on platforms without a strong adapter."""

    name = "unsupported"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        """Always fail instead of silently starting an unsafe process."""
        del record, command, environment
        raise ProcessIsolationError(self._reason)


def platform_process_isolator() -> ProcessIsolator:
    """Select the required OS isolation adapter."""
    if sys.platform == "darwin":
        return MacOSSeatbeltIsolator()
    if sys.platform.startswith("linux"):
        return LinuxBubblewrapIsolator()
    if sys.platform == "win32":
        from .windows_process_isolation import WindowsAppContainerIsolator

        return WindowsAppContainerIsolator()
    return UnsupportedProcessIsolator(
        f"Local Hub process isolation is unsupported on {sys.platform}.",
    )
