# -*- coding: utf-8 -*-
"""Session-scoped interactive terminals with bounded output replay."""
from __future__ import annotations

import asyncio
import codecs
import os
import signal
import struct
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Protocol

IDLE_TIMEOUT_SECONDS = 30 * 60
MAX_TERMINALS_PER_SESSION = 3
MAX_TERMINALS_TOTAL = 12
RING_FRAMES = 512
SUBSCRIBER_FRAMES = 64


@dataclass(frozen=True)
class TerminalEvent:
    """One ordered terminal output, exit, or replay-gap event."""

    seq: int
    type: str
    data: str = ""
    exit_code: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        """Return a JSON-safe event payload."""
        return {
            "seq": self.seq,
            "type": self.type,
            "data": self.data,
            "exit_code": self.exit_code,
        }


class TerminalBackend(Protocol):
    """Native terminal operations used by a terminal session."""

    async def read(self) -> str | None: ...

    async def write(self, data: str) -> None: ...

    async def resize(self, cols: int, rows: int) -> None: ...

    async def close(self) -> int | None: ...


class PosixPtyBackend:
    """Standard-library PTY backend for macOS and Linux."""

    def __init__(self, cwd: Path, cols: int, rows: int) -> None:
        if os.name != "posix":
            raise RuntimeError("POSIX_PTY_UNAVAILABLE")
        import pty  # pylint: disable=import-outside-toplevel

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._read_close_lock = threading.Lock()
        self._closed = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace",
        )
        self._decoder_flushed = False
        try:
            # pylint: disable-next=consider-using-with
            self._process = subprocess.Popen(
                [self._default_shell()],
                cwd=str(cwd),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
                env=self._safe_environment(),
            )
        except Exception:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        try:
            self._resize_sync(cols, rows)
        except Exception:
            self._closed = True
            self._terminate_and_close_sync()
            raise

    @staticmethod
    def _default_shell() -> str:
        candidates = [
            os.environ.get("SHELL", ""),
            "/bin/zsh",
            "/bin/bash",
            "/bin/sh",
        ]
        for shell in candidates:
            if shell and Path(shell).is_file() and os.access(shell, os.X_OK):
                return shell
        raise RuntimeError("NO_SUPPORTED_SHELL")

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = {
            "COLORTERM",
            "HOME",
            "LANG",
            "LC_ALL",
            "LOGNAME",
            "PATH",
            "TMPDIR",
            "USER",
        }
        environment = {
            key: value for key, value in os.environ.items() if key in allowed
        }
        environment["TERM"] = "xterm-256color"
        return environment

    async def read(self) -> str | None:
        if self._closed:
            return None

        def _read() -> bytes:
            with self._read_close_lock:
                try:
                    return os.read(self._master_fd, 4096)
                except OSError:
                    return b""

        data = await asyncio.to_thread(_read)
        if data:
            return self._decoder.decode(data)
        if not self._decoder_flushed:
            self._decoder_flushed = True
            tail = self._decoder.decode(b"", final=True)
            if tail:
                return tail
        return None

    async def write(self, data: str) -> None:
        if self._closed:
            raise RuntimeError("TERMINAL_CLOSED")
        payload = data.encode()

        def _write_all() -> None:
            offset = 0
            while offset < len(payload):
                written = os.write(self._master_fd, payload[offset:])
                if written <= 0:
                    raise BrokenPipeError("TERMINAL_WRITE_CLOSED")
                offset += written

        await asyncio.to_thread(_write_all)

    def _resize_sync(self, cols: int, rows: int) -> None:
        import fcntl  # pylint: disable=import-outside-toplevel
        import termios  # pylint: disable=import-outside-toplevel

        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, size)

    async def resize(self, cols: int, rows: int) -> None:
        if not self._closed:
            await asyncio.to_thread(self._resize_sync, cols, rows)

    def _terminate_and_close_sync(self) -> int | None:
        """Stop the child before closing the PTY master descriptor."""
        try:
            if self._process.poll() is None:
                try:
                    os.killpg(self._process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self._process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(self._process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self._process.wait()
        finally:
            with self._read_close_lock:
                try:
                    os.close(self._master_fd)
                except OSError:
                    pass
        return self._process.returncode

    async def close(self) -> int | None:
        if self._closed:
            return self._process.poll()
        self._closed = True
        return await asyncio.to_thread(self._terminate_and_close_sync)


class TerminalSession:
    """Own one PTY, bounded replay, and isolated subscribers."""

    def __init__(
        self,
        terminal_id: str,
        session_id: str,
        backend: TerminalBackend,
    ) -> None:
        self.id = terminal_id
        self.session_id = session_id
        self.backend = backend
        self._seq = 0
        self._ring: deque[TerminalEvent] = deque(maxlen=RING_FRAMES)
        self._subscribers: set[asyncio.Queue[TerminalEvent]] = set()
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._last_activity = asyncio.get_running_loop().time()
        self._pump_task = asyncio.create_task(self._pump())
        self._idle_task = asyncio.create_task(self._close_when_idle())

    @property
    def closed(self) -> bool:
        """Return whether native resources have been released."""
        return self._closed

    def _touch(self) -> None:
        self._last_activity = asyncio.get_running_loop().time()

    async def _pump(self) -> None:
        try:
            while not self._closed:
                data = await self.backend.read()
                if data is None:
                    break
                self._touch()
                self._broadcast("output", data=data)
        finally:
            if not self._closed:
                self._closed = True
                self._idle_task.cancel()
                exit_code = await self.backend.close()
                self._broadcast("exit", exit_code=exit_code)

    async def _close_when_idle(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(60)
                idle_for = (
                    asyncio.get_running_loop().time() - self._last_activity
                )
                if idle_for >= IDLE_TIMEOUT_SECONDS:
                    await self.close()
        except asyncio.CancelledError:
            return

    def _broadcast(
        self,
        event_type: str,
        *,
        data: str = "",
        exit_code: int | None = None,
    ) -> None:
        self._seq += 1
        event = TerminalEvent(self._seq, event_type, data, exit_code)
        self._ring.append(event)
        for queue in tuple(self._subscribers):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(TerminalEvent(event.seq - 1, "gap"))
            queue.put_nowait(event)

    async def write(self, data: str) -> None:
        self._touch()
        async with self._write_lock:
            await self.backend.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        self._touch()
        await self.backend.resize(cols, rows)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        current = asyncio.current_task()
        if self._idle_task is not current:
            self._idle_task.cancel()
        try:
            exit_code = await self.backend.close()
        finally:
            if self._pump_task is not current:
                if not self._pump_task.done():
                    self._pump_task.cancel()
                try:
                    await self._pump_task
                except asyncio.CancelledError:
                    pass
        self._broadcast("exit", exit_code=exit_code)

    async def subscribe(self, after_seq: int) -> AsyncIterator[TerminalEvent]:
        queue: asyncio.Queue[TerminalEvent] = asyncio.Queue(
            maxsize=SUBSCRIBER_FRAMES,
        )
        replay = tuple(self._ring)
        initially_closed = self._closed
        if not initially_closed:
            self._subscribers.add(queue)
        try:
            if replay and after_seq < replay[0].seq - 1:
                yield TerminalEvent(replay[0].seq - 1, "gap")
            for event in replay:
                if event.seq > after_seq:
                    yield event
            if initially_closed:
                return
            while True:
                event = await queue.get()
                yield event
                if event.type == "exit":
                    return
        finally:
            self._subscribers.discard(queue)


BackendFactory = Callable[[Path, int, int], TerminalBackend]


class TerminalManager:
    """Bounded in-memory terminal registry for one agent workspace."""

    def __init__(self, backend_factory: BackendFactory | None = None) -> None:
        self._backend_factory = backend_factory or PosixPtyBackend
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def capability() -> dict[str, str | bool | int]:
        """Describe native terminal availability and quotas."""
        available = os.name == "posix"
        return {
            "available": available,
            "backend": "posix-pty" if available else "",
            "reason": "" if available else "CONPTY_NOT_AVAILABLE",
            "max_per_session": MAX_TERMINALS_PER_SESSION,
        }

    async def create(
        self,
        session_id: str,
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalSession:
        async with self._lock:
            self._drop_closed()
            active = self.list_session(session_id)
            if len(active) >= MAX_TERMINALS_PER_SESSION:
                raise ValueError("TERMINAL_SESSION_LIMIT")
            if len(self._sessions) >= MAX_TERMINALS_TOTAL:
                raise ValueError("TERMINAL_AGENT_LIMIT")
            backend = await asyncio.to_thread(
                self._backend_factory,
                cwd,
                cols,
                rows,
            )
            terminal_id = f"term_{uuid.uuid4().hex}"
            session = TerminalSession(terminal_id, session_id, backend)
            self._sessions[terminal_id] = session
            return session

    def _drop_closed(self) -> None:
        self._sessions = {
            key: value
            for key, value in self._sessions.items()
            if not value.closed
        }

    def get(self, session_id: str, terminal_id: str) -> TerminalSession:
        """Return a terminal only when the session owns it."""
        session = self._sessions.get(terminal_id)
        if session is None or session.session_id != session_id:
            raise KeyError("TERMINAL_NOT_FOUND")
        return session

    def list_session(self, session_id: str) -> list[TerminalSession]:
        """List live terminals owned by one conversation session."""
        return [
            item
            for item in self._sessions.values()
            if item.session_id == session_id and not item.closed
        ]

    async def close(self, session_id: str, terminal_id: str) -> None:
        session = self.get(session_id, terminal_id)
        await session.close()
        self._sessions.pop(terminal_id, None)

    async def close_all(self) -> None:
        """Close every terminal owned by this manager."""
        await asyncio.gather(
            *(item.close() for item in tuple(self._sessions.values())),
            return_exceptions=True,
        )
        self._sessions.clear()
