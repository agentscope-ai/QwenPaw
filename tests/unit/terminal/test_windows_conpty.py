# -*- coding: utf-8 -*-
"""Platform-neutral tests for the threaded Windows ConPTY adapter."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import psutil
import pytest

from qwenpaw.terminal import backends
from qwenpaw.terminal.capture import BackgroundCapture
from qwenpaw.terminal.backends.windows_conpty import WindowsConPtyBackend
from qwenpaw.terminal.backends import windows_conpty
from qwenpaw.utils.io_utils import path_exists_async, read_text_async


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
async def test_conpty_terminates_complete_windows_process_tree(monkeypatch):
    process = _FakePtyProcess()
    capture = BackgroundCapture(1024)
    tree_kills: list[tuple[int, int]] = []
    loop_thread = threading.get_ident()

    def terminate_tree(pid: int) -> None:
        tree_kills.append((pid, threading.get_ident()))

    monkeypatch.setattr(windows_conpty.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_conpty,
        "terminate_windows_process_tree",
        terminate_tree,
    )
    backend = WindowsConPtyBackend(process, capture)

    await backend.close()

    assert [pid for pid, _thread in tree_kills] == [process.pid]
    assert tree_kills[0][1] != loop_thread
    assert process.closed is True


@pytest.mark.asyncio
async def test_conpty_spawn_passes_space_path_as_unquoted_argv(
    monkeypatch,
    tmp_path,
):
    process = _FakePtyProcess()
    captured: dict[str, object] = {}

    class FakePtyProcess:
        @staticmethod
        def spawn(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return process

    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(PtyProcess=FakePtyProcess),
    )
    shell = r"C:\Program Files\PowerShell\7\pwsh.exe"

    backend = await WindowsConPtyBackend.spawn(shell, tmp_path, {}, 1024)
    try:
        assert captured["argv"] == [shell, "-NoLogo", "-NoProfile"]
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="requires real ConPTY")
async def test_real_conpty_close_kills_child_and_grandchild(tmp_path):
    pid_file = tmp_path / "descendants.txt"
    grandchild = "import time; time.sleep(60)"
    child = (
        "import os, pathlib, subprocess, sys, time; "
        f"p=subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text("
        "f'{os.getpid()} {p.pid}', encoding='utf-8'); "
        "time.sleep(60)"
    )
    command = subprocess.list2cmdline([sys.executable, "-c", child])
    backend = await WindowsConPtyBackend.spawn(
        "cmd.exe",
        tmp_path,
        os.environ.copy(),
        64 * 1024,
    )
    descendant_pids: list[int] = []
    try:
        await backend.write(f"{command}\r\n".encode("utf-8"))
        for _ in range(100):
            if await path_exists_async(pid_file):
                values = (await read_text_async(pid_file)).split()
                descendant_pids = [int(value) for value in values]
                break
            await asyncio.sleep(0.05)
        assert len(descendant_pids) == 2
        assert all(psutil.pid_exists(pid) for pid in descendant_pids)

        await backend.close()

        for _ in range(100):
            if not any(psutil.pid_exists(pid) for pid in descendant_pids):
                break
            await asyncio.sleep(0.05)
        assert not any(psutil.pid_exists(pid) for pid in descendant_pids)
    finally:
        await backend.close()
        for pid in descendant_pids:
            try:
                psutil.Process(pid).kill()
            except psutil.Error:
                pass


@pytest.mark.asyncio
async def test_windows_backend_failure_uses_explicit_degraded_fallback(
    monkeypatch,
    tmp_path,
):
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


@pytest.mark.asyncio
async def test_unknown_windows_shell_uses_explicit_degraded_fallback(
    monkeypatch,
    tmp_path,
):
    degraded = object()

    async def pipe_fallback(*_args, **_kwargs):
        return degraded

    monkeypatch.setattr(backends.sys, "platform", "win32")
    monkeypatch.setattr(backends.PipeTerminalBackend, "spawn", pipe_fallback)

    result = await backends.spawn_terminal_backend(
        "nu.exe",
        tmp_path,
        {},
        1024,
        tty=True,
    )

    assert result is degraded
