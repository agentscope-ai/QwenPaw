# -*- coding: utf-8 -*-
"""Local sandbox — abstract base + None passthrough.

Implementation layer for the sandbox package. Hosts the shared
:class:`LocalSandbox` ABC that every platform backend subclasses, plus the
:class:`NoneSandbox` passthrough used for trusted / no-isolation execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import time
from abc import ABC, abstractmethod
from typing import List, Optional

from .config import (
    ExecutionResult,
    SandboxConfig,
    report_unenforced_config,
)

logger = logging.getLogger(__name__)

# Shell dispatch mirrors ``windows_unelevated_sandbox``'s
# ``_build_shell_command_line`` so a configured shell behaves the same
# whichever backend ends up running it.
_POWERSHELL_NAMES = frozenset(
    {"powershell", "powershell.exe", "pwsh", "pwsh.exe"},
)
_CMD_NAMES = frozenset({"cmd", "cmd.exe"})


def _platform_default_shell() -> str:
    """Return this platform's default shell.

    ``/bin/bash`` is not a usable default on Windows, where the equivalent
    is ``COMSPEC`` (cmd.exe).
    """
    if sys.platform == "win32":
        return os.environ.get("COMSPEC") or "cmd.exe"
    return os.environ.get("SHELL") or "/bin/bash"


def _resolve_shell(candidate: str) -> Optional[str]:
    """Resolve *candidate* to a runnable path, or None if it is not found.

    An absolute path is checked directly; a bare name such as ``cmd.exe``
    is looked up on PATH, which ``os.path.exists`` alone would reject.
    """
    if os.path.isabs(candidate):
        return candidate if os.path.exists(candidate) else None
    return shutil.which(candidate)


def _shell_basename(shell: str) -> str:
    """Lowercased basename of *shell*, tolerating either path separator.

    ``os.path.basename`` only splits on the host separator, so a Windows
    path inspected on POSIX would keep its directories and defeat the name
    match below. A POSIX filename may legally contain a backslash, but a
    shell path that does is pathological next to the Windows case this
    guards.
    """
    return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _shell_argv(shell: str, cmd: str) -> List[str]:
    """Build the argv that makes *shell* run the *cmd* string.

    cmd.exe takes ``/c``, PowerShell needs its non-interactive flags, and
    every POSIX shell takes ``-c``.
    """
    name = _shell_basename(shell)
    if name in _POWERSHELL_NAMES:
        return [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            cmd,
        ]
    if name in _CMD_NAMES:
        return [shell, "/c", cmd]
    return [shell, "-c", cmd]


# ═══════════════════════════════════════════════════════════════════════════════
# Abstract base
# ═══════════════════════════════════════════════════════════════════════════════


class LocalSandbox(ABC):
    """Lightweight sandbox abstract base. Per-tool-call lifecycle."""

    # Config fields this backend actually applies. Anything the caller
    # requests outside this set is reported at construction time, so a
    # backend can never drop a constraint silently. The empty default
    # means "enforces nothing" — a new subclass is loud until it declares
    # what it honours.
    _ENFORCED_FIELDS: frozenset = frozenset()

    # Per-field remediation text appended to the report, for constraints
    # whose failure mode the operator needs spelled out.
    _ENFORCEMENT_HINTS: dict = {}

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        report_unenforced_config(
            config,
            type(self).__name__,
            self._enforced_fields(),
            self._ENFORCEMENT_HINTS,
        )

    def _enforced_fields(self) -> frozenset:
        """Fields this backend applies *for the current config*.

        Overridden where enforcement is conditional — e.g. no backend can
        filter the network by domain, so ``network_allow`` only counts as
        enforced for the all-open / block-all postures.
        """
        return self._ENFORCED_FIELDS

    @property
    def config(self) -> SandboxConfig:
        return self._config

    @abstractmethod
    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a command inside the sandbox."""

    async def stop(self) -> None:
        """Tear down the sandbox and kill any straggler subprocesses."""
        if not (self._process and self._process.returncode is None):
            return
        try:
            if hasattr(os, "killpg"):
                # POSIX: signal the whole session so the shell's children
                # die with it, not just the shell.
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            else:
                # Windows has neither killpg nor SIGKILL -- calling them
                # raises AttributeError, which the handler below does not
                # catch. Terminating the shell is the best this backend
                # can do there.
                self._process.kill()
        except (ProcessLookupError, OSError):
            pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# None mode — passthrough (no isolation)
# ═══════════════════════════════════════════════════════════════════════════════


class NoneSandbox(LocalSandbox):
    """No isolation, executes directly.

    Used for trusted scenarios or resource tools. Enforces no filesystem,
    network or resource boundary whatsoever: every such constraint in the
    config is reported as ignored by :class:`LocalSandbox`.
    """

    _ENFORCED_FIELDS = frozenset({"shell_executable"})

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        cwd = cwd or self._config.workspace_dir
        configured = self._config.shell_executable
        shell = _resolve_shell(configured) if configured else None
        if configured and shell is None:
            # This backend declares shell_executable as enforced, so a
            # silent fall back would be the same lie the reporter exists
            # to prevent.
            logger.warning(
                "NoneSandbox: shell_executable=%s could not be resolved; "
                "falling back to the platform default.",
                configured,
            )
        if shell is None:
            default = _platform_default_shell()
            # Pass the unresolved name through when even the default is
            # missing: the spawn error names it, which beats guessing.
            shell = _resolve_shell(default) or default

        # Build subprocess env: inherit + apply env_vars (overrides)
        env = dict(os.environ)
        if self._config.env_vars:
            env.update(self._config.env_vars)

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *_shell_argv(shell, cmd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._config.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                exit_code=self._process.returncode or 0,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                timed_out=False,
                duration_ms=duration_ms,
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
        except asyncio.CancelledError:
            await self.stop()
            raise
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self.stop()
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
            )
