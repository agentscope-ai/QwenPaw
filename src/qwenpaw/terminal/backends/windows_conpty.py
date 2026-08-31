# -*- coding: utf-8 -*-
"""Windows ConPTY backend powered by pywinpty blocking worker threads."""

from __future__ import annotations

import asyncio
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

from ...utils.io_utils import run_sync_io
from ..capture import BackgroundCapture
from ..process_tree import terminate_windows_process_tree
from ..shells import shell_spec


def _startup_script(shell: str, marker: str) -> bytes:
    """Emit a readiness marker after the interactive shell has initialized."""
    spec = shell_spec(shell)
    if spec.family == "powershell":
        return (
            "function global:prompt { '' }\r\n"
            "[Console]::Out.WriteLine(([char]0x1e).ToString() + "
            f'"{marker}" + [char]0x1f)\r\n'
        ).encode("utf-8")
    return f"echo \x1e{marker}\x1f\r\n".encode("utf-8")


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
            if self.pid > 0 and sys.platform == "win32":
                await run_sync_io(
                    terminate_windows_process_tree,
                    self.pid,
                )
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
            shell_spec(shell).windows_conpty_argv(),
            cwd=str(cwd),
            env=env,
        )
        backend = cls(process, BackgroundCapture(capture_bytes))
        try:
            await backend._prepare_shell(shell)
        except BaseException:
            await backend.close()
            raise
        return backend

    async def _prepare_shell(self, shell: str) -> None:
        """Wait for shell startup to finish, then discard prompt noise."""
        marker = f"QWENPAW_READY_{secrets.token_hex(12)}"
        sentinel = b"\x1e" + marker.encode("ascii") + b"\x1f"
        cursor = self.capture.end_cursor
        await self.write(_startup_script(shell, marker))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10.0
        observed = self.capture.end_cursor
        while True:
            retained, _, _ = self.capture.retained_since(cursor)
            if sentinel in retained:
                # Allow the reader callback queued with the marker to append
                # the immediately following prompt before clearing startup
                # output from the public command stream.
                await asyncio.sleep(0)
                self.capture.discard_retained()
                return
            if self.supervisor.returncode is not None:
                raise RuntimeError("interactive shell exited during startup")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("interactive shell startup timed out")
            await self.capture.wait_for_change(observed, remaining)
            observed = self.capture.end_cursor

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
