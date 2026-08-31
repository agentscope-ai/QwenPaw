# -*- coding: utf-8 -*-
"""POSIX PTY backend using non-blocking event-loop fd callbacks."""

from __future__ import annotations

import asyncio
import errno
import os
import pty
import secrets
import select
import signal
import termios
from pathlib import Path

from ...utils.io_utils import run_sync_io
from ..capture import BackgroundCapture
from ..process_tree import ProcessSupervisor
from ..shells import shell_spec


def _open_pty() -> tuple[int, int]:
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    os.set_blocking(master, False)
    return master, slave


def _disable_echo(fd: int) -> None:
    """Restore no-echo mode after an interactive shell changes termios."""
    attrs = termios.tcgetattr(fd)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
            view = view[written:]
        except BlockingIOError:
            select.select([], [fd], [], 0.5)


def _interrupt_foreground(fd: int, session_id: int) -> None:
    """Signal the managed terminal's foreground process group."""
    foreground_pgid = 0
    try:
        candidate = os.tcgetpgrp(fd)
        if candidate > 0 and os.getsid(candidate) == session_id:
            foreground_pgid = candidate
    except (ProcessLookupError, PermissionError, OSError):
        pass

    target_pgid = foreground_pgid or session_id
    try:
        os.killpg(target_pgid, signal.SIGINT)
    except (ProcessLookupError, PermissionError, OSError):
        if target_pgid == session_id:
            return
        try:
            os.killpg(session_id, signal.SIGINT)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _startup_script(shell: str, marker: str) -> bytes:
    name = shell_spec(shell).name
    if name == "zsh":
        setup = (
            "unsetopt zle prompt_cr prompt_sp 2>/dev/null; PS1=''; PS2=''; "
            "PROMPT_EOL_MARK=''; HISTFILE=/dev/null"
        )
    elif name == "bash":
        setup = (
            "set +o emacs; set +o vi; PS1=''; PS2=''; "
            "PROMPT_COMMAND=''; HISTFILE=/dev/null"
        )
    else:
        setup = "PS1=''; PS2=''; ENV=''; HISTFILE=/dev/null"
    return f"{setup}; printf '\\036{marker}\\037\\n'\n".encode("utf-8")


class PosixPtyBackend:
    tty = True
    degraded = False

    def __init__(
        self,
        master_fd: int,
        process: asyncio.subprocess.Process,
        capture: BackgroundCapture,
    ) -> None:
        self.master_fd = master_fd
        self.supervisor = ProcessSupervisor(process)
        self.capture = capture
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._loop.add_reader(master_fd, self._read_ready)
        self._wait_task = asyncio.create_task(self._watch_process())

    @classmethod
    async def spawn(
        cls,
        shell: str,
        cwd: Path,
        env: dict[str, str],
        capture_bytes: int,
    ) -> "PosixPtyBackend":
        master, slave = await run_sync_io(_open_pty)
        child_env = dict(env)
        child_env.update(
            {
                "PS1": "",
                "PS2": "",
                "PROMPT_COMMAND": "",
                "PROMPT_EOL_MARK": "",
                "HISTFILE": os.devnull,
            },
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *shell_spec(shell).posix_pty_argv(),
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(cwd),
                env=child_env,
                start_new_session=True,
            )
        except BaseException:
            os.close(master)
            os.close(slave)
            raise
        os.close(slave)
        backend = cls(master, process, BackgroundCapture(capture_bytes))
        try:
            await backend._prepare_shell(shell)
        except BaseException:
            await backend.close()
            raise
        return backend

    async def _prepare_shell(self, shell: str) -> None:
        """Wait until startup files are done, then discard prompt noise."""
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
                await run_sync_io(_disable_echo, self.master_fd)
                # Drain any empty prompt emitted immediately after the marker.
                await asyncio.sleep(0)
                self._read_ready()
                self.capture.discard_retained()
                return
            if self.supervisor.returncode is not None:
                raise RuntimeError("interactive shell exited during startup")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("interactive shell startup timed out")
            await self.capture.wait_for_change(observed, remaining)
            observed = self.capture.end_cursor

    def _read_ready(self) -> None:
        budget = 256 * 1024
        try:
            while budget > 0:
                try:
                    data = os.read(self.master_fd, min(64 * 1024, budget))
                except BlockingIOError:
                    return
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        self._finish_reader()
                        return
                    raise
                if not data:
                    self._finish_reader()
                    return
                self.capture.append(data)
                budget -= len(data)
        except BaseException as exc:  # noqa: BLE001
            self._finish_reader(exc)

    def _finish_reader(self, error: BaseException | None = None) -> None:
        try:
            self._loop.remove_reader(self.master_fd)
        except (OSError, ValueError):
            pass
        self.capture.mark_eof(error)

    async def _watch_process(self) -> None:
        await self.supervisor.wait()
        # Drain bytes already queued on the PTY before EIO signals EOF. The
        # completion sentinel is commonly in this final kernel buffer.
        self._read_ready()

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("terminal is closed")
        await run_sync_io(_write_all, self.master_fd, data)

    async def interrupt(self) -> None:
        await run_sync_io(
            _interrupt_foreground,
            self.master_fd,
            self.supervisor.pid,
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._finish_reader()
        await self.supervisor.terminate()
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        if not self._wait_task.done():
            self._wait_task.cancel()
            try:
                await self._wait_task
            except asyncio.CancelledError:
                pass
        await self.capture.close()
