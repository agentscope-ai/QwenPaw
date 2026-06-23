# -*- coding: utf-8 -*-
"""Linux bubblewrap sandbox implementation.

Uses bubblewrap (bwrap) to construct a mount-namespace-based filesystem view.
This provides stronger filesystem isolation than Landlock alone:
  - deny_paths are truly invisible (not mounted at all)
  - /dev is a minimal synthetic devtmpfs (null, zero, urandom, tty, etc.)
  - PID namespace isolation via --unshare-pid
  - No HOME enumeration hacks needed for deny_paths

Limitations (current version):
  - Network is NOT isolated (no --unshare-net). Sandboxed processes have
    full network access. Network namespace isolation is planned for a
    future iteration.
  - deny_paths for individual files uses --ro-bind /dev/null (file appears
    empty rather than ENOENT). Directory-level deny uses --tmpfs (invisible).

Architecture:
    bwrap constructs the filesystem view, then execs the user command.
    The parent process waits for completion and captures stdout/stderr.

Reference:
    https://github.com/containers/bubblewrap
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import signal
import time
from typing import List, Optional

from .config import ExecutionResult
from .local_sandbox import LocalSandbox

logger = logging.getLogger(__name__)

# Regex to detect sandbox violations in stderr output.
_BWRAP_VIOLATION_RE = re.compile(
    r"\bPermission denied\b"
    r"|^bwrap:\s"
    r"|\bOperation not permitted\b"
    r"|\bEACCES\b",
    re.IGNORECASE | re.MULTILINE,
)


class BubblewrapSandbox(LocalSandbox):
    """Linux bubblewrap sandbox using mount namespaces.

    deny-default whitelist model:
      - Filesystem is read-only by default (--ro-bind / /) when
        allow_read_all=True, or starts empty (--tmpfs /) otherwise.
      - /dev is always a minimal synthetic devtmpfs (--dev /dev).
      - /tmp is always writable.
      - workspace_dir and mounts are layered with appropriate permissions.
      - deny_paths are masked with --tmpfs (invisible to sandboxed process).
      - PID namespace is isolated (--unshare-pid + --proc /proc).
    """

    def _find_bwrap(self) -> str:
        """Locate the bwrap binary.

        Raises:
            FileNotFoundError: if bwrap is not on PATH.
        """
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise FileNotFoundError(
                "bubblewrap (bwrap) not found on PATH; "
                "install it or switch to Landlock mode",
            )
        return bwrap

    def _build_bwrap_args(  # pylint: disable=too-many-branches
        self,
        cmd: str,
        cwd: str,
    ) -> List[str]:
        """Build the full bwrap command-line argument list.

        The mount order follows Codex conventions:
        1. Base filesystem (--ro-bind / / or --tmpfs /)
        2. --dev /dev (minimal device nodes)
        3. Always-writable paths (/tmp, /dev/shm)
        4. Writable mounts from config (workspace, etc.)
        5. Read-only mounts from config
        6. deny_paths masks (--tmpfs to hide)
        7. Namespace isolation (--unshare-user, --unshare-pid, --proc)
        8. -- /bin/sh -c <cmd>
        """
        config = self._config
        args: List[str] = []

        # Session and lifecycle
        args.extend(["--new-session", "--die-with-parent"])

        # --- Base filesystem ---
        if config.allow_read_all:
            # Full disk readable (deny-list mode)
            args.extend(["--ro-bind", "/", "/"])
        else:
            # Empty filesystem (allow-list mode)
            args.extend(["--tmpfs", "/"])
            # Mount system paths for basic operation
            system_paths = [
                "/usr",
                "/lib",
                "/lib64",
                "/bin",
                "/sbin",
                "/etc",
                "/proc",
                "/sys",
                "/run",
            ]
            for sp in system_paths:
                if os.path.exists(sp):
                    args.extend(["--ro-bind", sp, sp])
            # Mount declared read-only mounts
            for mount in config.mounts:
                if not mount.writable and os.path.exists(mount.path):
                    args.extend(["--ro-bind", mount.path, mount.path])

        # --- Minimal /dev ---
        args.extend(["--dev", "/dev"])

        # --- Always-writable paths ---
        always_writable = ["/tmp"]
        if os.path.exists("/dev/shm"):
            always_writable.append("/dev/shm")
        for p in always_writable:
            if os.path.exists(p):
                args.extend(["--bind", p, p])

        # --- Writable mounts (workspace + config mounts) ---
        for mount in config.mounts:
            if mount.writable and os.path.exists(mount.path):
                args.extend(["--bind", mount.path, mount.path])

        # --- deny_paths: mask with --tmpfs ---
        if config.deny_paths:
            for dp in config.deny_paths:
                expanded = os.path.expanduser(dp)
                if os.path.exists(expanded):
                    if os.path.isdir(expanded):
                        args.extend(["--tmpfs", expanded])
                    else:
                        # For files, bind /dev/null over them
                        args.extend(
                            ["--ro-bind", "/dev/null", expanded],
                        )

        # --- Namespace isolation ---
        # --unshare-user creates a user namespace; bwrap automatically
        # maps the calling uid/gid to uid 0/gid 0 inside the sandbox.
        # We add explicit --uid/--gid for clarity and cross-distro safety.
        args.extend(["--unshare-user", "--uid", "0", "--gid", "0"])
        args.extend(["--unshare-pid"])

        # --- Fresh /proc ---
        args.extend(["--proc", "/proc"])

        # --- Working directory ---
        if cwd and os.path.isdir(cwd):
            args.extend(["--chdir", cwd])

        # --- Command ---
        # Hardcode /bin/sh (POSIX-guaranteed) to avoid injection via
        # SHELL env var and ensure consistent cross-shell semantics.
        args.extend(["--", "/bin/sh", "-c", cmd])

        return args

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a command inside the bubblewrap sandbox."""
        cwd_resolved = cwd or self._config.workspace_dir
        if not os.path.isdir(cwd_resolved):
            cwd_resolved = self._config.workspace_dir

        start = time.monotonic()

        try:
            bwrap = self._find_bwrap()
        except FileNotFoundError as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=0,
            )

        bwrap_args = self._build_bwrap_args(cmd, cwd_resolved)
        full_cmd = [bwrap] + bwrap_args

        # Build subprocess environment
        env = dict(os.environ)
        if self._config.env_vars:
            env.update(self._config.env_vars)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._config.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Detect sandbox violation
            violation = None
            if self._process.returncode != 0 and _BWRAP_VIOLATION_RE.search(
                stderr,
            ):
                violation = stderr.strip()

            return ExecutionResult(
                exit_code=self._process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                duration_ms=duration_ms,
                sandbox_violation=violation,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self.stop()
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Command timed out",
                timed_out=True,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
            )

    async def stop(self) -> None:
        """Kill any running subprocess and reap zombie."""
        if self._process and self._process.returncode is None:
            try:
                os.killpg(
                    os.getpgid(self._process.pid),
                    signal.SIGKILL,
                )
            except (ProcessLookupError, OSError):
                pass
            try:
                await self._process.wait()
            except (ProcessLookupError, OSError):
                pass
