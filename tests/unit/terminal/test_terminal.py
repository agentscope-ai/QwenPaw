# -*- coding: utf-8 -*-
"""Tests for bounded capture and managed persistent terminals."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path

import pytest

from qwenpaw.terminal import BackgroundCapture, TerminalSessionManager


def test_capture_is_bounded_and_reports_omitted_bytes():
    capture = BackgroundCapture(max_retained_bytes=8)
    capture.append(b"12345")
    capture.append(b"67890")

    chunk = capture.poll(0, 100)

    assert chunk.data == b"34567890"
    assert chunk.omitted_bytes == 2
    assert chunk.original_bytes == 10
    assert capture.start_cursor == 2


def test_capture_can_discard_startup_noise_without_resetting_cursor():
    capture = BackgroundCapture(max_retained_bytes=32)
    capture.append(b"startup-noise")
    cursor = capture.end_cursor

    capture.discard_retained()
    capture.append(b"command-output")

    chunk = capture.poll(cursor, 32)
    assert chunk.data == b"command-output"
    assert chunk.omitted_bytes == 0


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_persistent_pty_keeps_cwd_and_environment(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    env = os.environ.copy()
    first = await manager.execute(
        "export QWENPAW_TERMINAL_TEST=kept; cd /",
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=env,
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=64 * 1024,
    )
    try:
        second = await manager.execute(
            'printf "%s:%s" "$QWENPAW_TERMINAL_TEST" "$PWD"',
            session_id=first.session_id,
            shell="/bin/sh",
            cwd=tmp_path,
            env=env,
            tty=True,
            persistent=True,
            timeout=5,
            yield_time=2,
            max_output_bytes=64 * 1024,
        )
        assert second.exit_code == 0
        assert second.output == "kept:/"
        assert second.tty is True
        assert second.degraded is False
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32" or not Path("/bin/zsh").exists(),
    reason="zsh PTY behavior",
)
async def test_zsh_pty_ignores_user_rc_and_prompt_noise(tmp_path):
    (tmp_path / ".zshrc").write_text(
        "print SHOULD_NOT_APPEAR; PS1='NOISY> '",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["ZDOTDIR"] = str(tmp_path)
    manager = TerminalSessionManager(tmp_path)
    first = await manager.execute(
        "export QWENPAW_ZSH_TEST=kept; cd /",
        session_id=None,
        shell="/bin/zsh",
        cwd=tmp_path,
        env=env,
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=64 * 1024,
    )
    try:
        assert first.output == ""
        second = await manager.execute(
            'printf "%s:%s" "$QWENPAW_ZSH_TEST" "$PWD"',
            session_id=first.session_id,
            shell="/bin/zsh",
            cwd=tmp_path,
            env=env,
            tty=True,
            persistent=True,
            timeout=5,
            yield_time=2,
            max_output_bytes=64 * 1024,
        )
        assert second.output == "kept:/"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_interactive_child_receives_write_stdin_not_protocol(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    program = 'value=input("name: "); print("hello " + value, flush=True)'
    command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(program)}"
    first = await manager.execute(
        command,
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=0.1,
        max_output_bytes=64 * 1024,
    )
    try:
        assert first.running is True

        final = await manager.interact(
            first.session_id,
            "QwenPaw\n",
            yield_time=2,
            max_output_bytes=64 * 1024,
            terminate=False,
        )

        assert final.running is False
        assert final.exit_code == 0
        assert first.output + final.output == "name: hello QwenPaw"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_long_command_polls_incrementally_then_auto_closes(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    first = await manager.execute(
        "printf start; sleep 0.3; printf end",
        session_id=None,
        shell="/bin/sh",
        cwd=Path(tmp_path),
        env=os.environ.copy(),
        tty=True,
        persistent=False,
        timeout=5,
        yield_time=0.05,
        max_output_bytes=64 * 1024,
    )
    assert first.running is True
    assert first.session_id

    final = await manager.interact(
        first.session_id,
        "",
        yield_time=2,
        max_output_bytes=64 * 1024,
        terminate=False,
    )

    assert final.running is False
    assert final.exit_code == 0
    assert first.output + final.output == "startend"
    assert final.session_id is None
    assert manager.active_sessions == 0


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_nonpersistent_session_stays_until_output_is_drained(tmp_path):
    manager = TerminalSessionManager(tmp_path, max_retained_bytes=32 * 1024)
    program = 'import sys; sys.stdout.write("x" * 100000); sys.stdout.flush()'
    command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(program)}"
    result = await manager.execute(
        command,
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=False,
        timeout=5,
        yield_time=2,
        max_output_bytes=1024,
    )
    delivered = result.output_bytes
    omitted = result.omitted_bytes
    try:
        assert result.running is False
        assert result.output_drained is False
        assert result.session_id is not None
        assert manager.active_sessions == 1

        while not result.output_drained:
            result = await manager.interact(
                result.session_id,
                "",
                yield_time=0,
                max_output_bytes=1024,
                terminate=False,
            )
            delivered += result.output_bytes
            omitted += result.omitted_bytes

        assert result.session_id is None
        assert result.exit_code == 0
        assert result.original_bytes == 100_000
        assert delivered + omitted == 100_000
        assert manager.active_sessions == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_shutdown_kills_managed_process_group(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    result = await manager.execute(
        "sleep 30",
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=60,
        yield_time=0.05,
        max_output_bytes=1024,
    )
    assert result.running is True
    await manager.shutdown()
    assert manager.active_sessions == 0


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_ctrl_c_recovers_persistent_shell_to_idle(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    first = await manager.execute(
        "sleep 30",
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=60,
        yield_time=0.05,
        max_output_bytes=1024,
    )
    interrupted = await manager.interact(
        first.session_id,
        "\x03",
        yield_time=2,
        max_output_bytes=1024,
        terminate=False,
    )
    try:
        assert interrupted.running is False
        assert interrupted.exit_code == 130
        follow_up = await manager.execute(
            "printf alive",
            session_id=first.session_id,
            shell="/bin/sh",
            cwd=tmp_path,
            env=os.environ.copy(),
            tty=True,
            persistent=True,
            timeout=5,
            yield_time=2,
            max_output_bytes=1024,
        )
        assert follow_up.output == "alive"
        assert follow_up.exit_code == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_idle_janitor_reclaims_persistent_session(tmp_path):
    manager = TerminalSessionManager(tmp_path, idle_ttl_seconds=0.05)
    result = await manager.execute(
        "true",
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=1024,
    )
    assert result.running is False
    assert manager.active_sessions == 1
    for _ in range(20):
        if manager.active_sessions == 0:
            break
        await asyncio.sleep(0.02)
    assert manager.active_sessions == 0
    await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_reusing_idle_session_cancels_due_expiry_task(tmp_path):
    manager = TerminalSessionManager(tmp_path, idle_ttl_seconds=60)
    first = await manager.execute(
        "true",
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=1024,
    )
    session = manager._sessions[first.session_id]
    manager._cancel_expiry(first.session_id)
    manager._expiry_due(first.session_id, session.last_activity)

    second = await manager.execute(
        "printf reused",
        session_id=first.session_id,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=1024,
    )
    try:
        assert second.output == "reused"
        assert manager.active_sessions == 1
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_idle_session_rejects_raw_stdin_commands(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    first = await manager.execute(
        "true",
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=1024,
    )
    try:
        with pytest.raises(RuntimeError, match="session is idle"):
            await manager.interact(
                first.session_id,
                "echo bypass\n",
                yield_time=0,
                max_output_bytes=1024,
                terminate=False,
            )
    finally:
        await manager.shutdown()
