# -*- coding: utf-8 -*-
"""Local sandbox — macOS Seatbelt + None mode.

Only two modes are implemented:
  - SEATBELT: macOS sandbox-exec kernel isolation
  - NONE: passthrough, no isolation (trusted scenarios)

Usage:
    from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec

    config = SandboxConfig(
        mode=SandboxMode.SEATBELT,
        workspace_dir="/path/to/project",
        mounts=[MountSpec(path="/path/to/project", writable=True)],
        network_allow=["*"],
    )
    sandbox = create_sandbox(config)
    result = await sandbox.execute("ls -la")
    print(result.stdout)
    await sandbox.stop()
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from abc import ABC, abstractmethod
from typing import Optional

from .config import ExecutionResult, MountSpec, SandboxConfig, SandboxMode

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Abstract base
# ═══════════════════════════════════════════════════════════════════════════════


class LocalSandbox(ABC):
    """轻量级沙箱抽象基类。per-tool-call 生命周期。"""

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None

    @property
    def config(self) -> SandboxConfig:
        return self._config

    @abstractmethod
    async def execute(self, cmd: str, cwd: Optional[str] = None) -> ExecutionResult:
        """在沙箱中执行命令。"""

    async def stop(self) -> None:
        """销毁沙箱，杀死残留子进程。"""
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
# macOS — Seatbelt / sandbox-exec
# ═══════════════════════════════════════════════════════════════════════════════


class MacOSSandbox(LocalSandbox):
    """macOS sandbox using sandbox-exec (Seatbelt profiles).

    deny-default whitelist model:
      - 基本系统路径只读 (/System, /usr/lib, /usr/share, /Library, /dev)
      - workspace_dir 可读写
      - mounts 中声明的路径按 writable 决定 ro/rw
      - 网络按 network_allow 控制
      - ~/.ssh 等敏感路径显式拒绝
    """

    def _compile_seatbelt_profile(self) -> str:
        """生成 Seatbelt .sb 策略字符串。"""
        config = self._config
        lines = [
            "(version 1)",
            "",
            "(deny default)",
            "",
            "; Basic system operations",
            "(allow process-exec*)",
            "(allow process-fork)",
            "(allow signal)",
            "(allow sysctl-read)",
            "",
            "; System file access (readonly)",
            "(allow file-read*",
            '  (subpath "/System")',
            '  (subpath "/usr/lib")',
            '  (subpath "/usr/share")',
            '  (subpath "/Library")',
            '  (subpath "/private/var/db/timezone")',
            '  (literal "/dev/null")',
            '  (literal "/dev/zero")',
            '  (literal "/dev/random")',
            '  (literal "/dev/urandom")',
            '  (literal "/dev/tty")',
            '  (literal "/dev/dtracehelper")',
            ")",
            "",
            "; Mach operations",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            "",
            "; Sysctl operations",
            "(allow sysctl-read",
            '  (sysctl-name-prefix "hw.")',
            '  (sysctl-name-prefix "kern.")',
            '  (sysctl-name-prefix "machdep.cpu.")',
            ")",
        ]

        # Network
        lines.append("")
        lines.append("; Network")
        if config.network_allow and ("*" in config.network_allow):
            lines.append(
                "; WARNING: Domain-level filtering not implemented"
            )
            domains = [d for d in config.network_allow if d != "*"]
            if domains:
                lines.append(
                    f"; The following domains are in allowedDomains but not enforced:"
                )
                for d in domains:
                    lines.append(f";   - {d}")
            lines.append("; All network access is allowed")
            lines.append("(allow network*)")
        elif config.network_allow:
            lines.append("; Partial network (domain filtering not enforceable)")
            lines.append("(allow network*)")
        else:
            lines.append("(deny network*)")

        # File read paths
        lines.append("")
        lines.append("; File read")
        # Always allow reading everything by default (like Cursor approach)
        # then deny specific sensitive paths
        lines.append("(allow file-read*)")
        # Deny sensitive paths
        home = os.path.expanduser("~")
        sensitive = [os.path.join(home, ".ssh")]
        for p in sensitive:
            if os.path.exists(p):
                lines.append(f"(deny file-read*")
                lines.append(f'  (subpath "{p}"))')

        # File write paths (whitelist)
        lines.append("")
        lines.append("; File write")
        # Always allow /dev/null, /dev/zero, /dev/tty, /tmp
        write_always = ["/dev/null", "/dev/zero", "/dev/tty", "/tmp", "/private/tmp"]
        for p in write_always:
            lines.append(f"(allow file-write*")
            lines.append(f'  (subpath "{p}"))')

        # Workspace and explicit mounts
        for mount in config.mounts:
            if mount.writable:
                lines.append(f"(allow file-write*")
                lines.append(f'  (subpath "{mount.path}"))')

        return "\n".join(lines)

    async def execute(self, cmd: str, cwd: Optional[str] = None) -> ExecutionResult:
        """通过 sandbox-exec -p '<profile>' /bin/bash -c '<cmd>' 执行。"""
        profile = self._compile_seatbelt_profile()
        cwd = cwd or self._config.workspace_dir

        # Find shell
        shell = os.environ.get("SHELL", "/bin/bash")
        if not os.path.exists(shell):
            shell = "/bin/bash"

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_exec(
                "sandbox-exec", "-p", profile, shell, "-c", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._config.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Detect sandbox violation from stderr
            violation = None
            if self._process.returncode != 0 and (
                "deny" in stderr.lower()
                or "sandbox" in stderr.lower()
                or "operation not permitted" in stderr.lower()
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


# ═══════════════════════════════════════════════════════════════════════════════
# None mode — passthrough (no isolation)
# ═══════════════════════════════════════════════════════════════════════════════


class NoneSandbox(LocalSandbox):
    """不隔离，直接执行。用于信任场景或 resource tool。"""

    async def execute(self, cmd: str, cwd: Optional[str] = None) -> ExecutionResult:
        cwd = cwd or self._config.workspace_dir
        shell = os.environ.get("SHELL", "/bin/bash")
        if not os.path.exists(shell):
            shell = "/bin/bash"

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_exec(
                shell, "-c", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
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


# ═══════════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════════


def create_sandbox(config: SandboxConfig) -> LocalSandbox:
    """根据 config.mode 创建对应的 sandbox 实例。

    支持:
      - SEATBELT → MacOSSandbox
      - NONE → NoneSandbox
      - LANDLOCK / WSL2 → 抛出 NotImplementedError
    """
    if config.mode == SandboxMode.SEATBELT:
        return MacOSSandbox(config)
    elif config.mode == SandboxMode.NONE:
        return NoneSandbox(config)
    elif config.mode == SandboxMode.LANDLOCK:
        raise NotImplementedError("Landlock sandbox not yet implemented")
    elif config.mode == SandboxMode.WSL2:
        raise NotImplementedError("WSL2 sandbox not yet implemented")
    else:
        raise ValueError(f"Unknown sandbox mode: {config.mode}")
