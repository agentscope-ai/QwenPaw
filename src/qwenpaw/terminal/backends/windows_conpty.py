# -*- coding: utf-8 -*-
"""Windows ConPTY backend powered by pywinpty blocking worker threads."""

from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path
from typing import Any

from ...utils.io_utils import run_sync_io
from ..capture import BackgroundCapture


def _basename(shell: str) -> str:
    return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _command_line(shell: str) -> str:
    name = _basename(shell)
    if name in {"cmd", "cmd.exe"}:
        argv = [shell, "/D", "/Q", "/K"]
    elif name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        argv = [shell, "-NoLogo", "-NoProfile"]
    else:
        argv = [shell]
    return subprocess.list2cmdline(argv)


class _WinPtySupervisor:
    def __init__(self, process: Any) -> None:
        self.process = process
        self.pid = int(getattr(process, "pid", 0) or 0)
        self._returncode: int | None = None
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def record_exit(self) -> None:
        value = getattr(self.process, "exitstatus", None)
        if callable(value):
            try:
                value = value()
            except Exception:  # noqa: BLE001
                value = None
        self._returncode = int(value) if isinstance(value, int) else 0

    async def interrupt(self) -> None:
        if self._closed:
            return
        await run_sync_io(self.process.write, "\x03")

    async def terminate(self, _grace: float = 2.0) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                await run_sync_io(self.process.close, True)
            except TypeError:
                await run_sync_io(self.process.close)
            except Exception:  # noqa: BLE001
                pass
            self.record_exit()


class WindowsConPtyBackend:
    """Drain ConPTY on one daemon thread; never block the asyncio loop."""

    tty = True
    degraded = False

    def __init__(
        self,
        process: Any,
        capture: BackgroundCapture,
    ) -> None:
        self.process = process
        self.capture = capture
        self.supervisor = _WinPtySupervisor(process)
        self._loop = asyncio.get_running_loop()
        self._stop = threading.Event()
        self._closed = False
        self._reader = threading.Thread(
            target=self._reader_main,
            name=f"qwenpaw-conpty-{self.supervisor.pid}",
            daemon=True,
        )
        self._reader.start()

    @classmethod
    async def spawn(
        cls,
        shell: str,
        cwd: Path,
        env: dict[str, str],
        capture_bytes: int,
    ) -> "WindowsConPtyBackend":
        from winpty import PtyProcess  # type: ignore[import-not-found]

        process = await run_sync_io(
            PtyProcess.spawn,
            _command_line(shell),
            cwd=str(cwd),
            env=env,
        )
        return cls(process, BackgroundCapture(capture_bytes))

    def _reader_main(self) -> None:
        error: BaseException | None = None
        try:
            while not self._stop.is_set():
                try:
                    value = self.process.read(64 * 1024)
                except EOFError:
                    break
                if not value:
                    break
                data = (
                    value
                    if isinstance(value, bytes)
                    else value.encode("utf-8")
                )
                self._loop.call_soon_threadsafe(self.capture.append, data)
        except BaseException as exc:  # noqa: BLE001
            error = exc
        finally:
            self.supervisor.record_exit()
            try:
                self._loop.call_soon_threadsafe(self.capture.mark_eof, error)
            except RuntimeError:
                pass

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("terminal is closed")
        await run_sync_io(self.process.write, data.decode("utf-8"))

    async def interrupt(self) -> None:
        await self.supervisor.interrupt()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        await self.supervisor.terminate()
        await run_sync_io(self._reader.join, 2.0)
        await self.capture.close()
