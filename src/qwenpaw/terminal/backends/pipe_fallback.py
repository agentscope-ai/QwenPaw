# -*- coding: utf-8 -*-
"""Cross-platform persistent pipe fallback (explicitly not a PTY)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..capture import BackgroundCapture
from ..process_tree import ProcessSupervisor


def _basename(shell: str) -> str:
    return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _argv(shell: str) -> list[str]:
    name = _basename(shell)
    if name in {"cmd", "cmd.exe"}:
        return [shell, "/D", "/Q", "/K"]
    if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return [shell, "-NoLogo", "-NoProfile", "-Command", "-"]
    return [shell]


class PipeTerminalBackend:
    tty = False
    degraded = True

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        capture: BackgroundCapture,
    ) -> None:
        self.process = process
        self.supervisor = ProcessSupervisor(process)
        self.capture = capture
        if process.stdout is None:
            raise RuntimeError("pipe backend stdout was not created")
        capture.start_stream_reader(process.stdout)

    @classmethod
    async def spawn(
        cls,
        shell: str,
        cwd: Path,
        env: dict[str, str],
        capture_bytes: int,
    ) -> "PipeTerminalBackend":
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
        else:
            kwargs["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(
            *_argv(shell),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=env,
            **kwargs,
        )
        return cls(process, BackgroundCapture(capture_bytes))

    async def write(self, data: bytes) -> None:
        if self.process.stdin is None or self.process.stdin.is_closing():
            raise RuntimeError("terminal stdin is closed")
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def interrupt(self) -> None:
        await self.supervisor.interrupt()

    async def close(self) -> None:
        if (
            self.process.stdin is not None
            and not self.process.stdin.is_closing()
        ):
            self.process.stdin.close()
        await self.supervisor.terminate()
        await self.capture.close()
