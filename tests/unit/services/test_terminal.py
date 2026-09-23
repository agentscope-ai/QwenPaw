# -*- coding: utf-8 -*-
"""Exercise real PTYs as well as terminal ownership and bounded replay."""
# pylint: disable=protected-access

import asyncio
import os
import shlex
import socket
import sys
import threading
import time
from unittest.mock import MagicMock
from uuid import uuid4

import psutil
import pytest

from qwenpaw.services import terminal

if os.name != "nt":
    import fcntl


def test_windows_shell_falls_back_when_comspec_is_missing(monkeypatch):
    monkeypatch.setattr(terminal.os, "name", "nt")
    monkeypatch.delenv("COMSPEC", raising=False)
    monkeypatch.setattr(terminal.shutil, "which", lambda _name: None)

    assert terminal.shell_command() == ["cmd.exe"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor inheritance")
async def test_pty_does_not_inherit_service_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    manager = terminal.TerminalManager()
    owner = ("alice", "agent", "group")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        descriptor = fcntl.fcntl(listener.fileno(), fcntl.F_DUPFD, 128)
        os.set_inheritable(descriptor, True)
        try:
            info = await asyncio.to_thread(
                manager.create,
                owner,
                tmp_path,
                asyncio.get_running_loop(),
            )
            session = manager.get(owner, info["id"])
            await asyncio.to_thread(session.write, "stty -echo\r")
            script = (
                "import os\n"
                "try:\n"
                f" os.fstat({descriptor})\n"
                "except OSError:\n"
                " print('FD_' + 'CLOSED')\n"
                "else:\n"
                " print('FD_' + 'LEAKED')\n"
            )
            await asyncio.to_thread(
                session.write,
                f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}\r",
            )
            await read_until(session, "FD_CLOSED")
            assert os.get_inheritable(descriptor)
            assert os.fstat(descriptor) == os.fstat(listener.fileno())
        finally:
            await asyncio.to_thread(manager.shutdown)
            os.close(descriptor)


async def read_until(session, needle, cursor=0):
    """Collect output until a known shell result, with a hard timeout."""

    async def collect():
        text = ""
        after = cursor
        while needle not in text:
            chunk = await session.output(after)
            text += chunk["data"]
            after = chunk["cursor"]
            if chunk["exited"]:
                break
        assert needle in text, repr(text)
        return text, after

    return await asyncio.wait_for(collect(), 8)


@pytest.mark.skipif(os.name == "nt", reason="Unix shell syntax")
async def test_real_pty_cwd_unicode_resize_interrupt_and_cleanup(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "test-only-secret")
    cwd = tmp_path / "目录 with spaces"
    cwd.mkdir()
    manager = terminal.TerminalManager()
    owner = ("alice", "agent-a", "group-a")
    info = await asyncio.to_thread(
        manager.create,
        owner,
        cwd,
        asyncio.get_running_loop(),
    )
    session = manager.get(owner, info["id"])
    pid = session.process.pid
    try:
        await asyncio.to_thread(session.write, "stty -echo\r")
        await asyncio.to_thread(session.resize, 37, 101)
        script = (
            "import os; print('CWD=' + os.getcwd()); "
            "print('UTF=' + chr(20320) + chr(22909)); "
            "os.write(1, b'\\xff\\n'); "
            "print('SIZE=' + str(os.get_terminal_size())); "
            "print('SECRET=' + str('QWENPAW_RUNTIME_INTERNAL_TOKEN' "
            "in os.environ))"
        )
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}\r"
        await asyncio.to_thread(session.write, command)
        text, cursor = await read_until(session, "SECRET=False")
        assert f"CWD={cwd}" in text
        assert "UTF=你好" in text
        assert "columns=101, lines=37" in text
        await asyncio.to_thread(session.write, "sleep 30\r")
        for _ in range(100):
            if psutil.Process(pid).children():
                break
            await asyncio.sleep(0.01)
        await asyncio.to_thread(session.write, "\x03")
        await asyncio.to_thread(session.write, "printf 'INTERRUPTED\\n'\r")
        _, cursor = await read_until(session, "INTERRUPTED", cursor)
        await asyncio.to_thread(session.write, "sleep 60 &\r")
        children = []
        for _ in range(100):
            children = psutil.Process(pid).children(recursive=True)
            if children:
                break
            await asyncio.sleep(0.01)
        assert children
    finally:
        await asyncio.to_thread(manager.shutdown)
    assert not psutil.pid_exists(pid)
    assert not session.reader.is_alive()
    assert all(
        not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
        for child in children
    )


@pytest.mark.skipif(os.name == "nt", reason="Unix shell syntax")
async def test_close_releases_write_blocked_by_pty_backpressure(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SHELL", "/bin/sh")
    manager = terminal.TerminalManager()
    owner = ("alice", "agent", "group")
    info = manager.create(owner, tmp_path, asyncio.get_running_loop())
    session = manager.get(owner, info["id"])
    writer_done = threading.Event()

    def fill_input_queue():
        try:
            while True:
                session.write("x" * 16384)
        except (EOFError, OSError, ValueError):
            pass
        finally:
            writer_done.set()

    try:
        session.write("stty -echo -icanon; sleep 60\r")
        for _ in range(100):
            if psutil.Process(session.process.pid).children():
                break
            await asyncio.sleep(0.01)
        writer = threading.Thread(target=fill_input_queue, daemon=True)
        writer.start()
        await asyncio.sleep(0.3)
        assert not writer_done.is_set()

        closer = threading.Thread(target=session.close, daemon=True)
        closer.start()
        closer.join(timeout=3)

        closed_in_time = not closer.is_alive()
        if not closed_in_time:
            root = psutil.Process(session.process.pid)
            for child in root.children(recursive=True):
                child.kill()
            root.kill()
            closer.join(timeout=3)
        assert closed_in_time
        assert writer_done.wait(1)
    finally:
        manager.shutdown()


@pytest.mark.skipif(os.name == "nt", reason="Unix shell syntax")
async def test_exit_replay_and_detached_reclamation(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    manager = terminal.TerminalManager()
    owner = ("alice", "agent", "group")
    info = await asyncio.to_thread(
        manager.create,
        owner,
        tmp_path,
        asyncio.get_running_loop(),
    )
    session = manager.get(owner, info["id"])
    try:
        await asyncio.to_thread(session.write, "printf 'DONE\\n'; exit 7\r")
        await read_until(session, "DONE")
        for _ in range(100):
            if session.exited:
                break
            await asyncio.sleep(0.02)
        output = await session.output(0)
        assert output["exited"]
        assert output["exit_code"] == 7
        assert "DONE" in output["data"]
        session.last_seen = time.monotonic() - terminal.DETACHED_TTL - 1
        await asyncio.to_thread(manager.reap)
        assert manager.list(owner) == []
        assert session.closed
    finally:
        await asyncio.to_thread(manager.shutdown)


async def test_replay_is_bounded_and_cursor_detects_loss():
    session = terminal.TerminalSession.__new__(terminal.TerminalSession)
    session.lock = threading.Lock()
    session.loop = asyncio.get_running_loop()
    session.changed = asyncio.Event()
    session.notified = False
    session.buffer = ""
    session.cursor = 0
    session.exited = True
    session.exit_code = 0
    session._append("你" * (terminal.MAX_BUFFER + 100))
    assert len(session.buffer) == terminal.MAX_BUFFER
    result = await session.output(0)
    assert result["reset"]
    assert len(result["data"]) == terminal.MAX_CHUNK
    assert result["cursor"] == 100 + terminal.MAX_CHUNK
    assert not result["exited"]
    next_result = await session.output(result["cursor"])
    assert not next_result["reset"]
    assert next_result["cursor"] == 100 + terminal.MAX_CHUNK * 2


def test_append_tolerates_event_loop_shutdown_race():
    session = terminal.TerminalSession.__new__(terminal.TerminalSession)
    session.lock = threading.Lock()
    session.loop = MagicMock()
    session.loop.is_closed.return_value = False
    session.loop.call_soon_threadsafe.side_effect = RuntimeError("closed")
    session.changed = MagicMock()
    session.notified = False
    session.buffer = ""
    session.cursor = 0

    session._append("done")

    assert session.buffer == "done"
    assert session.cursor == 4
    assert not session.notified


async def test_limits_and_owner_isolation(tmp_path, monkeypatch):
    def fake_session(owner, _cwd, _loop):
        session = MagicMock()
        session.id = str(uuid4())
        session.owner = owner
        session.info.return_value = {"id": session.id}
        return session

    monkeypatch.setattr(terminal, "TerminalSession", fake_session)
    manager = terminal.TerminalManager()
    owner = ("alice", "a", "g")
    loop = asyncio.get_running_loop()
    for _ in range(8):
        manager.create(owner, tmp_path, loop)
    with pytest.raises(ValueError, match="this conversation"):
        manager.create(owner, tmp_path, loop)
    for index in range(24):
        manager.create((f"user-{index}", "a", "g"), tmp_path, loop)
    with pytest.raises(ValueError, match="service capacity"):
        manager.create(("extra", "a", "g"), tmp_path, loop)
    terminal_id = manager.list(owner)[0]["id"]
    for foreign in [
        ("bob", "a", "g"),
        ("alice", "b", "g"),
        ("alice", "a", "h"),
    ]:
        assert manager.list(foreign) == []
        with pytest.raises(KeyError):
            manager.get(foreign, terminal_id)
        with pytest.raises(KeyError):
            manager.close(foreign, terminal_id)
    manager.close(owner, terminal_id)
    assert len(manager.list(owner)) == 7
    manager.create(owner, tmp_path, loop)
    manager.shutdown()
    with pytest.raises(ValueError, match="shutting down"):
        manager.create(owner, tmp_path, loop)


async def test_slow_creation_does_not_block_other_manager_operations(
    tmp_path,
    monkeypatch,
):
    started = threading.Event()
    release = threading.Event()

    def slow_session(owner, _cwd, _loop):
        started.set()
        assert release.wait(3)
        session = MagicMock()
        session.id = str(uuid4())
        session.owner = owner
        session.info.return_value = {"id": session.id}
        return session

    monkeypatch.setattr(terminal, "TerminalSession", slow_session)
    manager = terminal.TerminalManager()
    owner = ("alice", "agent", "group")

    loop = asyncio.get_running_loop()
    creator = threading.Thread(
        target=lambda: manager.create(owner, tmp_path, loop),
    )
    creator.start()
    try:
        assert started.wait(1)
        probe = threading.Thread(target=lambda: manager.list(owner))
        probe.start()
        probe.join(timeout=1)
        assert not probe.is_alive()
        assert manager.list(owner) == []
    finally:
        release.set()
        creator.join(timeout=3)
    assert not creator.is_alive()
    assert len(manager.list(owner)) == 1


async def test_failed_creation_releases_reserved_capacity(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        terminal,
        "TerminalSession",
        MagicMock(side_effect=OSError("spawn failed")),
    )
    manager = terminal.TerminalManager()
    owner = ("alice", "agent", "group")

    with pytest.raises(OSError, match="spawn failed"):
        manager.create(owner, tmp_path, asyncio.get_running_loop())

    assert not manager.creating
