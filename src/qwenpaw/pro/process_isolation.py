# -*- coding: utf-8 -*-
"""Fail-closed OS process isolation for local Pro runtimes."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .models import RuntimeRecord


class ProcessIsolationError(RuntimeError):
    """Raised when the required local isolation boundary is unavailable."""


@dataclass(frozen=True)
class IsolatedLaunch:
    """Prepared process command and environment."""

    command: list[str]
    environment: dict[str, str]


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


def _read_roots(environment: Mapping[str, str]) -> list[Path]:
    source_root = Path(__file__).resolve().parents[2]
    roots = {
        Path(sys.executable).resolve(),
        Path(sys.prefix).resolve(),
        source_root,
    }
    if source_root.name == "src":
        repository_root = source_root.parent
        roots.add(repository_root / "website" / "public" / "docs")
        roots.add(repository_root / "console" / "dist")
    python_path = environment.get("PYTHONPATH", "")
    for value in python_path.split(os.pathsep):
        if value:
            roots.add(Path(value).expanduser().resolve())
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
            "/etc",
        ):
            if Path(path).exists():
                args.extend(["--ro-bind", path, path])
        for path in _read_roots(environment):
            args.extend(["--ro-bind", str(path), str(path)])
        args.extend(
            [
                "--bind",
                str(runtime_root),
                str(runtime_root),
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
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
        marker = runtime_root.parent / (f"qwenpaw-pro-forbidden-{os.getpid()}")
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
        profile = self._profile(record, environment)
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
        environment: Mapping[str, str],
    ) -> str:
        runtime_root = _runtime_root(record)
        read_paths = [
            Path("/System"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/Library"),
            Path("/private/var/db/timezone"),
            *_read_roots(environment),
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
            "(allow file-read*)",
        ]
        protected_paths = {
            Path.home().resolve(),
            runtime_root.parent.parent.resolve(),
        }
        for path in sorted(protected_paths, key=str):
            value = self._escape(path)
            lines.append(f'(deny file-read* (subpath "{value}"))')
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
            f"qwenpaw-pro-forbidden-{os.getpid()}"
        )
        forbidden.write_text("forbidden", encoding="utf-8")
        command = f'touch "{allowed}" && test ! -r "{forbidden}"'
        try:
            result = subprocess.run(
                [
                    self._executable,
                    "-f",
                    str(profile_path),
                    "/bin/sh",
                    "-c",
                    command,
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
        if result.returncode != 0:
            detail = result.stderr.strip() or "isolation probe failed"
            raise ProcessIsolationError(
                f"Seatbelt isolation is unavailable: {detail}",
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
        return UnsupportedProcessIsolator(
            "Local Pro runtimes require a Windows AppContainer adapter. "
            "Unsafe bare-process fallback is disabled.",
        )
    return UnsupportedProcessIsolator(
        f"Local Pro process isolation is unsupported on {sys.platform}.",
    )
