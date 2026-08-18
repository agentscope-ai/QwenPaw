# -*- coding: utf-8 -*-
"""Platform-neutral tests for the threaded Windows ConPTY adapter."""

from __future__ import annotations

import threading

import pytest

from qwenpaw.terminal.capture import BackgroundCapture
from qwenpaw.terminal.backends.windows_conpty import WindowsConPtyBackend


class _FakePtyProcess:
    pid = 1234
    exitstatus = 0

    def __init__(self) -> None:
        self._reads = ["hello", EOFError()]
        self.write_thread: int | None = None
        self.writes: list[str] = []
        self.closed = False

    def read(self, _size: int):
        value = self._reads.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, value: str) -> None:
        self.write_thread = threading.get_ident()
        self.writes.append(value)

    def close(self, _force: bool = False) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_conpty_reads_and_writes_off_event_loop_thread():
    process = _FakePtyProcess()
    capture = BackgroundCapture(1024)
    backend = WindowsConPtyBackend(process, capture)
    loop_thread = threading.get_ident()

    await capture.wait_for_change(0, 1.0)
    await backend.write("输入".encode("utf-8"))
    chunk = capture.poll(0, 1024)

    assert chunk.data == b"hello"
    assert process.writes == ["输入"]
    assert process.write_thread != loop_thread
    await backend.close()
    assert process.closed is True


@pytest.mark.asyncio
async def test_windows_backend_failure_uses_explicit_degraded_fallback(
    monkeypatch,
    tmp_path,
):
    import qwenpaw.terminal.backends as backends

    degraded = object()

    async def fail_conpty(*_args, **_kwargs):
        raise RuntimeError("no conpty")

    async def pipe_fallback(*_args, **_kwargs):
        return degraded

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(
        "qwenpaw.terminal.backends.windows_conpty.WindowsConPtyBackend.spawn",
        fail_conpty,
    )
    monkeypatch.setattr(backends.PipeTerminalBackend, "spawn", pipe_fallback)

    result = await backends.spawn_terminal_backend(
        "cmd.exe",
        tmp_path,
        {},
        1024,
        tty=True,
    )

    assert result is degraded
