# -*- coding: utf-8 -*-
"""Cross-platform ownership and termination of a subprocess tree."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys

from ..utils.io_utils import run_sync_io


def _taskkill(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


class ProcessSupervisor:
    """The unique lifecycle owner for one shell and its process group."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.pid = process.pid
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    async def wait(self) -> int:
        return await self.process.wait()

    async def interrupt(self) -> None:
        if self.process.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                self.process.send_signal(
                    getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM),
                )
            else:
                os.killpg(self.pid, signal.SIGINT)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    async def terminate(self, grace: float = 2.0) -> None:
        async with self._lock:
            if self._closed:
                return
            if self.process.returncode is None:
                if sys.platform == "win32":
                    await run_sync_io(_taskkill, self.pid)
                else:
                    try:
                        os.killpg(self.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=grace)
                except asyncio.TimeoutError:
                    if sys.platform == "win32":
                        await run_sync_io(_taskkill, self.pid)
                    else:
                        try:
                            os.killpg(self.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass
            self._closed = True
