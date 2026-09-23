# -*- coding: utf-8 -*-
"""Bounded, runtime-owned interactive terminals independent of HTTP clients."""

import asyncio
import importlib
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import psutil

MAX_BUFFER = 262144
MAX_CHUNK = 32768
DETACHED_TTL = 3600


def terminal_unavailable_reason():
    """Probe optional native dependencies without breaking app startup."""
    if sys.platform == "win32":
        try:
            importlib.import_module("winpty")
        except (ImportError, OSError):
            return "dependency_missing"
    return None


def native_pty():
    """Load platform-specific code only when a terminal is requested."""
    if sys.platform == "win32":
        return importlib.import_module(
            ".terminal_windows",
            __package__,
        ).WindowsPty
    return importlib.import_module(".terminal_posix", __package__).PosixPty


def shell_command() -> list[str]:
    """Select an installed interactive shell without evaluating shell text."""
    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell.exe")
        return (
            [shell, "-NoLogo"]
            if shell
            else [
                os.environ.get("COMSPEC", "cmd.exe"),
            ]
        )
    shell = os.environ.get("SHELL") or "/bin/sh"
    if not Path(shell).is_file():
        shell = "/bin/sh"
    return [shell, "-i"]


class TerminalSession:
    """One PTY with a bounded character cursor and coalesced notifications."""

    def __init__(self, owner, cwd, loop):
        self.id = str(uuid4())
        self.owner = owner
        self.cwd = str(cwd)
        self.command = shell_command()
        self.title = Path(self.command[0]).stem
        self.loop = loop
        self.changed = asyncio.Event()
        self.lock = threading.Lock()
        self.io_lock = threading.Lock()
        self.buffer = ""
        self.cursor = 0
        self.exited = False
        self.closed = False
        self.exit_code = None
        self.last_seen = time.monotonic()
        self.notified = False
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
        # Runtime authentication must never be inherited by user commands.
        for key in tuple(env):
            if key.startswith("QWENPAW_RUNTIME_") or "SHUTDOWN_TOKEN" in key:
                env.pop(key)
        self.process = native_pty().spawn(
            self.command,
            cwd=self.cwd,
            env=env,
            dimensions=(24, 80),
        )
        try:
            self.root = psutil.Process(self.process.pid)
        except psutil.Error:
            self.root = None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def info(self):
        """Return public metadata, without output or environment values."""
        return {
            "id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "exited": self.exited,
            "exit_code": self.exit_code,
        }

    def _notify(self):
        with self.lock:
            self.notified = False
        self.changed.set()

    def _append(self, data):
        with self.lock:
            self.buffer = (self.buffer + data)[-MAX_BUFFER:]
            self.cursor += len(data)
            if not self.notified and not self.loop.is_closed():
                self.notified = True
                try:
                    self.loop.call_soon_threadsafe(self._notify)
                except RuntimeError:
                    # The loop may close after is_closed() during shutdown.
                    self.notified = False

    def _read(self):
        try:
            while not self.closed:
                data = self.process.read(4096)
                if data:
                    self._append(data)
        except (EOFError, OSError):
            pass
        finally:
            try:
                # PTY EOF can precede the child's waitable exit status.
                for _ in range(20):
                    if not self.process.isalive():
                        break
                    time.sleep(0.01)
                self.exit_code = self.process.exitstatus
            except (OSError, AttributeError):
                pass
            self.exited = True
            self._append("")

    async def output(self, after):
        """Wait for output without occupying a thread-pool worker."""
        self.last_seen = time.monotonic()
        self.changed.clear()
        if after == self.cursor and not self.exited:
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass
        with self.lock:
            start = self.cursor - len(self.buffer)
            reset = after < start or after > self.cursor
            offset = max(0, after - start) if not reset else 0
            data = self.buffer[offset : offset + MAX_CHUNK]
            cursor = start + offset + len(data)
            return {
                "data": data,
                "cursor": cursor,
                "reset": reset,
                "exited": self.exited and cursor == self.cursor,
                "exit_code": self.exit_code,
            }

    def write(self, data):
        """Serialize writes with resize and teardown."""
        with self.io_lock:
            if self.closed or self.exited:
                raise ValueError("Terminal has exited")
            self.last_seen = time.monotonic()
            self.process.write(data)

    def resize(self, rows, cols):
        """Resize the real PTY, including full-screen terminal programs."""
        with self.io_lock:
            if not self.closed and not self.exited:
                self.process.setwinsize(rows, cols)

    def close(self):
        """Terminate shell descendants and release the PTY descriptor."""
        with self.io_lock:
            if self.closed:
                return
            self.closed = True
            try:
                children = (
                    self.root.children(recursive=True)
                    if self.root and self.root.is_running()
                    else []
                )
            except psutil.Error:
                children = []
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            # Closing BufferedRWPair first waits on the reader's lock. Stop
            # the process before closing its PTY so blocking read sees EOF.
            try:
                if self.root and self.root.is_running():
                    self.root.kill()
            except psutil.Error:
                pass
            try:
                self.process.close(force=True)
            except (EOFError, OSError):
                pass
            psutil.wait_procs(children, timeout=1)
        self.reader.join(timeout=2)
        self.exited = True
        self._append("")


class TerminalManager:
    """Keep per-principal/agent/group terminals and reclaim detached shells."""

    def __init__(self):
        self.sessions = {}
        self.creating = {}
        self.lock = threading.RLock()
        self.stopping = False

    def _release_creation(self, owner):
        remaining = self.creating.get(owner, 0) - 1
        if remaining > 0:
            self.creating[owner] = remaining
        else:
            self.creating.pop(owner, None)

    def list(self, owner):
        """List only terminals belonging to this exact owner tuple."""
        with self.lock:
            found = [s for s in self.sessions.values() if s.owner == owner]
            for session in found:
                session.last_seen = time.monotonic()
            return [s.info() for s in found]

    def create(self, owner, cwd, loop):
        """Reserve capacity under lock, then start the PTY without it."""
        with self.lock:
            if self.stopping:
                raise ValueError("Terminal service is shutting down")
            count = sum(s.owner == owner for s in self.sessions.values())
            count += self.creating.get(owner, 0)
            if count >= 8 or len(self.sessions) >= 32:
                raise ValueError("Terminal limit reached; close a tab first")
            if len(self.sessions) + sum(self.creating.values()) >= 32:
                raise ValueError("Terminal limit reached; close a tab first")
            self.creating[owner] = self.creating.get(owner, 0) + 1
        try:
            session = TerminalSession(owner, cwd, loop)
        except BaseException:
            with self.lock:
                self._release_creation(owner)
            raise
        with self.lock:
            self._release_creation(owner)
            if self.stopping:
                should_close = True
            else:
                should_close = False
                self.sessions[session.id] = session
        if should_close:
            session.close()
            raise ValueError("Terminal service is shutting down")
        return session.info()

    def get(self, owner, terminal_id):
        """Hide foreign IDs behind the same response as nonexistent IDs."""
        with self.lock:
            session = self.sessions.get(terminal_id)
            if session is None or session.owner != owner:
                raise KeyError(terminal_id)
            session.last_seen = time.monotonic()
            return session

    def close(self, owner, terminal_id):
        """Remove and stop a single owned terminal."""
        with self.lock:
            session = self.get(owner, terminal_id)
            del self.sessions[terminal_id]
        session.close()

    def reap(self):
        """Reclaim sessions with no attached UI for one hour."""
        now = time.monotonic()
        with self.lock:
            expired = [
                s
                for s in self.sessions.values()
                if now - s.last_seen > DETACHED_TTL
            ]
            for session in expired:
                del self.sessions[session.id]
        for session in expired:
            session.close()

    def shutdown(self):
        """Close all terminals before application shutdown finishes."""
        with self.lock:
            self.stopping = True
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.close()
