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
import signal
import time
from abc import ABC, abstractmethod
from typing import Optional

from .config import (
    ExecutionResult,
    SandboxConfig,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Abstract base
# ═══════════════════════════════════════════════════════════════════════════════


class LocalSandbox(ABC):
    """Lightweight sandbox abstract base. Per-tool-call lifecycle."""

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None

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
        if self._process and self._process.returncode is None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
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

    Used for trusted scenarios or resource tools.
    """

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        cwd = cwd or self._config.workspace_dir
        shell = os.environ.get("SHELL", "/bin/bash")
        if not os.path.exists(shell):
            shell = "/bin/bash"

        # Build subprocess env: inherit + apply env_vars (overrides)
        env = dict(os.environ)
        if self._config.env_vars:
            env.update(self._config.env_vars)

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_exec(
                shell,
                "-c",
                cmd,
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
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
            )
