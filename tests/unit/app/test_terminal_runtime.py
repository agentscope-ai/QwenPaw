# -*- coding: utf-8 -*-
"""Tests for the bounded interactive terminal runtime."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import threading
from pathlib import Path

import pytest

from qwenpaw.app.terminal_runtime import (
    MAX_TERMINALS_PER_SESSION,
    PosixPtyBackend,
    TerminalManager,
)


class FakeBackend:
    """In-memory backend used to verify runtime coordination."""

    def __init__(self, _cwd: Path, _cols: int, _rows: int) -> None:
        self.reads: asyncio.Queue[str | None] = asyncio.Queue()
        self.writes: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.closed = False

    async def read(self) -> str | None:
        return await self.reads.get()

    async def write(self, data: str) -> None:
        self.writes.append(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.sizes.append((cols, rows))

    async def close(self) -> int:
        self.closed = True
        await self.reads.put(None)
        return 0


@pytest.mark.asyncio
async def test_reconnect_replays_only_new_events(tmp_path: Path) -> None:
    backend = FakeBackend(tmp_path, 80, 24)
    manager = TerminalManager(lambda *_args: backend)
    session = await manager.create("session-a", tmp_path, 80, 24)
    await backend.reads.put("one")
    await backend.reads.put("two")
    await asyncio.sleep(0.01)

    event = await anext(session.subscribe(1))

    assert event.seq == 2
    assert event.data == "two"
    await manager.close_all()


@pytest.mark.asyncio
async def test_session_ownership_and_quota(tmp_path: Path) -> None:
    manager = TerminalManager(FakeBackend)
    sessions = [
        await manager.create("session-a", tmp_path, 80, 24)
        for _ in range(MAX_TERMINALS_PER_SESSION)
    ]

    with pytest.raises(KeyError, match="TERMINAL_NOT_FOUND"):
        manager.get("session-b", sessions[0].id)
    with pytest.raises(ValueError, match="TERMINAL_SESSION_LIMIT"):
        await manager.create("session-a", tmp_path, 80, 24)

    await manager.close_all()


@pytest.mark.asyncio
async def test_write_resize_and_close_reach_backend(tmp_path: Path) -> None:
    backend = FakeBackend(tmp_path, 80, 24)
    manager = TerminalManager(lambda *_args: backend)
    session = await manager.create("session-a", tmp_path, 80, 24)

    await session.write("pwd\n")
    await session.resize(120, 40)
    await manager.close("session-a", session.id)

    assert backend.writes == ["pwd\n"]
    assert backend.sizes == [(120, 40)]
    assert backend.closed is True
    assert manager.list_session("session-a") == []


@pytest.mark.asyncio
async def test_posix_close_terminates_child_before_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, int]] = []

    class Process:
        pid = 42
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: int | None = None) -> int:
            events.append(("wait", timeout or 0))
            self.returncode = -signal.SIGTERM
            return self.returncode

    backend = object.__new__(PosixPtyBackend)
    backend._closed = False
    backend._master_fd = 29
    backend._read_close_lock = threading.Lock()
    backend._process = Process()
    monkeypatch.setattr(
        os,
        "killpg",
        lambda _pid, sig: events.append(("signal", sig)),
    )
    monkeypatch.setattr(
        os,
        "close",
        lambda fd: events.append(("close", fd)),
    )

    await backend.close()

    assert events == [
        ("signal", signal.SIGTERM),
        ("wait", 1),
        ("close", 29),
    ]


@pytest.mark.asyncio
async def test_posix_close_keeps_event_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_started = threading.Event()
    release_close = threading.Event()

    class Process:
        pid = 42
        returncode = 0

        def poll(self) -> int:
            return self.returncode

    backend = object.__new__(PosixPtyBackend)
    backend._closed = False
    backend._master_fd = 29
    backend._read_close_lock = threading.Lock()
    backend._process = Process()

    def blocking_close(_fd: int) -> None:
        close_started.set()
        assert release_close.wait(timeout=1)

    monkeypatch.setattr(os, "close", blocking_close)
    close_task = asyncio.create_task(backend.close())
    assert await asyncio.to_thread(close_started.wait, 1)
    await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
    release_close.set()
    await asyncio.wait_for(close_task, timeout=1)


@pytest.mark.asyncio
async def test_close_does_not_cancel_reader_before_backend_close(
    tmp_path: Path,
) -> None:
    class OrderedBackend(FakeBackend):
        def __init__(self, cwd: Path, cols: int, rows: int) -> None:
            super().__init__(cwd, cols, rows)
            self.read_started = asyncio.Event()
            self.release_read = asyncio.Event()
            self.reader_cancelled = False

        async def read(self) -> str | None:
            self.read_started.set()
            try:
                await self.release_read.wait()
            except asyncio.CancelledError:
                self.reader_cancelled = True
                raise
            return None

        async def close(self) -> int:
            assert self.reader_cancelled is False
            self.closed = True
            self.release_read.set()
            await asyncio.sleep(0)
            return 0

    backend = OrderedBackend(tmp_path, 80, 24)
    manager = TerminalManager(lambda *_args: backend)
    session = await manager.create("session-a", tmp_path, 80, 24)
    await backend.read_started.wait()

    await session.close()

    assert backend.closed is True
    assert backend.reader_cancelled is False
