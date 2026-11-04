# -*- coding: utf-8 -*-
"""Opt-in resource monitoring shared by shell execution backends."""

import asyncio
import os
import threading
from contextvars import ContextVar
from typing import Callable, Optional

import psutil

SHELL_GUARD: ContextVar[Optional["ShellGuard"]] = ContextVar(
    "shell_guard",
    default=None,
)
_OUTPUT_CAPTURE_BYTES = 1024 * 1024


def parse_shell_memory_limit(value: str) -> Optional[int]:
    """Parse a MiB ceiling; zero disables protection and None means auto."""
    if value == "auto":
        return None
    if value.isdecimal():
        return int(value)
    raise ValueError("Use 0, auto, or a positive integer for the memory limit")


class ShellGuard:
    """Monitor one command independently of its asyncio event loop."""

    def __init__(self, memory_limit: int, output_limit: int):
        self.memory_limit = memory_limit
        self.output_limit = output_limit
        self.failure = ""
        self._output_bytes = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._processes: set[psutil.Process] = set()
        self._root: Optional[psutil.Process] = None
        self._output_size: Optional[Callable[[], int]] = None

    @classmethod
    def from_environment(cls, output_limit: int) -> Optional["ShellGuard"]:
        """Leave the default path free of memory probes and threads."""
        requested = parse_shell_memory_limit(
            os.environ.get("QWENPAW_SHELL_MEMORY_LIMIT_MB", "0"),
        )
        if requested == 0:
            return None
        if requested is None:
            requested = 4096
        limit = min(
            requested * 1024 * 1024,
            psutil.virtual_memory().available // 2,
        )
        if limit <= 0:
            raise ValueError("No available memory for shell execution")
        return cls(limit, output_limit)

    def watch(self, pid: int, output_size: Optional[Callable[[], int]]):
        """Register the actual command process, not sandbox setup helpers."""
        try:
            self._root = psutil.Process(pid)
            self._processes.add(self._root)
        except psutil.NoSuchProcess:
            return
        self._output_size = output_size
        self._thread = threading.Thread(
            target=self._monitor,
            name="qwenpaw-shell-guard",
            daemon=True,
        )
        self._thread.start()

    def fail(self, reason: str):
        """Record the first protection failure across output readers."""
        with self._lock:
            if not self.failure:
                self.failure = reason

    def account_output(self, size: int):
        """Count drained bytes without retaining unbounded output."""
        with self._lock:
            self._output_bytes += size
            if self._output_bytes > self.output_limit and not self.failure:
                self.failure = (
                    f"Shell output limit exceeded ({self.output_limit} bytes)"
                )

    def _kill(self):
        processes = list(self._processes - {self._root})
        if self._root is not None:
            processes.append(self._root)
        for process in processes:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _monitor(self):
        while not self._stop.is_set():
            try:
                # Retain identities to follow observed, reparented children.
                if self._root is not None and self._root.is_running():
                    self._processes.update(
                        self._root.children(recursive=True),
                    )
                rss = 0
                for process in tuple(self._processes):
                    try:
                        if process.is_running():
                            rss += process.memory_info().rss
                        else:
                            self._processes.discard(process)
                    except psutil.NoSuchProcess:
                        self._processes.discard(process)
                if rss > self.memory_limit:
                    self.fail(
                        "Shell memory limit exceeded "
                        f"(RSS {rss} bytes > {self.memory_limit} bytes)",
                    )
                if self._output_size:
                    if self._output_size() > self.output_limit:
                        self.fail(
                            "Shell output limit exceeded "
                            f"({self.output_limit} bytes)",
                        )
            except psutil.NoSuchProcess:
                pass
            except (psutil.AccessDenied, OSError) as error:
                self.fail(f"Shell resource monitoring failed: {error}")
            if self.failure:
                self._kill()
            self._stop.wait(0.25)

    def close(self):
        """Stop monitoring before releasing this invocation's processes."""
        self._stop.set()
        if self._thread:
            self._thread.join()
            self._kill()


def watch_shell_process(
    pid: int,
    output_size: Optional[Callable[[], int]] = None,
):
    """Register only processes launched by a guarded shell invocation."""
    guard = SHELL_GUARD.get()
    if guard is not None:
        guard.watch(pid, output_size)


class ShellOutputBuffer:
    """Bound retained pipe output only inside a guarded shell call."""

    def __init__(self):
        self._guard = SHELL_GUARD.get()
        self._data = bytearray()
        self._truncated = False

    def append(self, data: bytes):
        if self._guard is None:
            self._data.extend(data)
            return
        self._guard.account_output(len(data))
        remaining = max(0, _OUTPUT_CAPTURE_BYTES - len(self._data))
        self._data.extend(data[:remaining])
        self._truncated |= len(data) > remaining

    def value(self) -> bytes:
        suffix = b"\n[output truncated]" if self._truncated else b""
        return bytes(self._data) + suffix


async def communicate_shell_process(process):
    """Drain sandbox pipes with bounded capture when protection is enabled."""
    if SHELL_GUARD.get() is None:
        return await process.communicate()
    watch_shell_process(process.pid)

    async def read(stream):
        buffer = ShellOutputBuffer()
        while data := await stream.read(65536):
            buffer.append(data)
        return buffer.value()

    tasks = [
        asyncio.create_task(read(process.stdout)),
        asyncio.create_task(read(process.stderr)),
        asyncio.create_task(process.wait()),
    ]
    try:
        stdout, stderr, _ = await asyncio.gather(*tasks)
        return stdout, stderr
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
