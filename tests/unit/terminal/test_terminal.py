# -*- coding: utf-8 -*-
"""Tests for bounded capture and managed persistent terminals."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.terminal import BackgroundCapture, TerminalSessionManager
from qwenpaw.terminal.models import SessionState
from qwenpaw.terminal.session import TerminalSession


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


# This deterministic stream-boundary test intentionally drives the session's
# parser state without starting an OS-specific backend.
# pylint: disable=protected-access
def test_completion_marker_is_hidden_at_every_stream_split():
    token = "a" * 24
    user_output = b"user"

    for line_ending in (b"\n", b"\r\n"):
        marker = f"\x1eQWENPAW_DONE_{token}:0\x1f".encode() + line_ending
        for split_at in range(1, len(marker)):
            _assert_completion_marker_split(
                token,
                marker,
                split_at,
                user_output,
            )


def test_powershell_protocol_uses_cross_version_control_char_syntax():
    backend = SimpleNamespace(tty=True, degraded=False)
    session = TerminalSession("term_test", backend, "pwsh.exe")

    wrapped = session._wrap_command("Write-Output ok", "a" * 24).decode()
    probe = session._completion_probe().decode()

    for script in (wrapped, probe):
        assert "`u001e" not in script
        assert "`u001f" not in script
        assert "[char]0x1e" in script
        assert "[char]0x1f" in script


def _assert_completion_marker_split(
    token: str,
    marker: bytes,
    split_at: int,
    user_output: bytes,
) -> None:
    capture = BackgroundCapture()
    backend = SimpleNamespace(
        capture=capture,
        supervisor=SimpleNamespace(returncode=None),
        tty=True,
        degraded=False,
    )
    session = TerminalSession("term_test", backend, "/bin/sh")
    session._wrap_command("true", token)
    session.state = SessionState.RUNNING
    session._command_started_at = time.monotonic()

    capture.append(user_output + marker[:split_at])
    session._refresh_state()
    outputs: list[str] = []
    while True:
        before = session._public_cursor
        partial = session._make_result(1)
        outputs.append(partial.output)
        assert partial.original_bytes == len(user_output), split_at
        if partial.next_cursor == before:
            break

    assert partial.running is True, split_at
    capture.append(marker[split_at:])
    session._refresh_state()
    for _ in range(len(marker) + 2):
        final = session._make_result(1)
        outputs.append(final.output)
        if final.output_drained:
            break

    assert final.output_drained is True, split_at
    assert final.exit_code == 0, split_at
    assert final.original_bytes == len(user_output), split_at
    assert "".join(outputs) == user_output.decode(), split_at
    assert "\x1e" not in "".join(outputs), split_at


# pylint: enable=protected-access


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
        assert first.output + final.output == "name: hello QwenPaw\r\n"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_interactive_input_fragments_are_withheld_until_newline(
    tmp_path,
):
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
        partial_preview = await manager.preview_input(first.session_id, "Qwen")
        await manager.authorize_input(
            first.session_id,
            "Qwen",
            partial_preview,
        )
        partial = await manager.interact(
            first.session_id,
            "Qwen",
            yield_time=2,
            max_output_bytes=64 * 1024,
            terminate=False,
        )
        assert partial.running is True
        assert partial.output == ""

        final_preview = await manager.preview_input(
            first.session_id,
            "Paw\n",
        )
        assert final_preview == "QwenPaw\n"
        await manager.authorize_input(
            first.session_id,
            "Paw\n",
            final_preview,
        )
        final = await manager.interact(
            first.session_id,
            "Paw\n",
            yield_time=2,
            max_output_bytes=64 * 1024,
            terminate=False,
        )
        assert final.running is False
        assert final.exit_code == 0
        assert first.output + final.output == "name: hello QwenPaw\r\n"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_raw_input_mode_delivers_single_key_without_newline(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    program = (
        "import os,sys,termios,tty; fd=sys.stdin.fileno(); "
        "old=termios.tcgetattr(fd); tty.setcbreak(fd); "
        "print('ready', flush=True); "
        "value=os.read(fd,1); termios.tcsetattr(fd,termios.TCSADRAIN,old); "
        "print('key:' + value.decode(), flush=True)"
    )
    command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(program)}"
    first = await manager.execute(
        command,
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        input_mode="raw",
        timeout=5,
        yield_time=2,
        max_output_bytes=64 * 1024,
    )
    try:
        assert first.running is True
        assert first.output == "ready\r\n"
        preview = await manager.preview_input(first.session_id, "q")
        assert preview == "q"
        await manager.authorize_input(first.session_id, "q", preview)

        final = await manager.interact(
            first.session_id,
            "q",
            yield_time=2,
            max_output_bytes=64 * 1024,
            terminate=False,
        )

        assert final.running is False
        assert final.exit_code == 0
        assert "key:q\r\n" in first.output + final.output
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_async_factory_resolves_workspace_off_event_loop(
    tmp_path,
    monkeypatch,
):
    loop_thread = threading.get_ident()
    resolve_threads: list[int] = []
    real_resolve = Path.resolve

    def tracked_resolve(path, *args, **kwargs):
        resolve_threads.append(threading.get_ident())
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", tracked_resolve)

    manager = await TerminalSessionManager.from_workspace(tmp_path)
    try:
        assert manager.workspace_dir == real_resolve(tmp_path)
        assert resolve_threads
        assert loop_thread not in resolve_threads
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="requires PowerShell")
async def test_persistent_powershell_does_not_reuse_stale_native_exit_code(
    tmp_path,
):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell is unavailable")
    manager = TerminalSessionManager(tmp_path)
    first = await manager.execute(
        "cmd.exe /d /c exit 7",
        session_id=None,
        shell=shell,
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=64 * 1024,
    )
    try:
        assert first.exit_code == 7
        second = await manager.execute(
            "Write-Output ok",
            session_id=first.session_id,
            shell=shell,
            cwd=tmp_path,
            env=os.environ.copy(),
            tty=True,
            persistent=True,
            timeout=5,
            yield_time=2,
            max_output_bytes=64 * 1024,
        )
        assert second.output == "ok\r\n"
        assert second.exit_code == 0

        failed = await manager.execute(
            "Write-Error failed",
            session_id=first.session_id,
            shell=shell,
            cwd=tmp_path,
            env=os.environ.copy(),
            tty=True,
            persistent=True,
            timeout=5,
            yield_time=2,
            max_output_bytes=64 * 1024,
        )
        assert failed.exit_code == 1
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
@pytest.mark.parametrize("max_output_bytes", [1, 2, 3, 5])
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_output_reconstructs_utf8_ansi_and_crlf_across_chunks(
    tmp_path,
    max_output_bytes,
):
    manager = TerminalSessionManager(tmp_path)
    raw_output = "\x1b[31m输入🙂\x1b[0m\n".encode("utf-8")
    program = (
        f"import sys; sys.stdout.buffer.write({raw_output!r}); "
        "sys.stdout.buffer.flush()"
    )
    command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(program)}"
    result = await manager.execute(
        command,
        session_id=None,
        shell="/bin/sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        tty=True,
        persistent=True,
        timeout=5,
        yield_time=2,
        max_output_bytes=max_output_bytes,
    )
    outputs = [result.output]
    delivered_bytes = result.output_bytes
    omitted_bytes = result.omitted_bytes
    previous_cursor = result.next_cursor
    try:
        while not result.output_drained:
            result = await manager.interact(
                result.session_id,
                "",
                yield_time=0,
                max_output_bytes=max_output_bytes,
                terminate=False,
            )
            assert result.next_cursor >= previous_cursor
            previous_cursor = result.next_cursor
            outputs.append(result.output)
            delivered_bytes += result.output_bytes
            omitted_bytes += result.omitted_bytes

        expected = "输入🙂\r\n"
        assert "".join(outputs) == expected
        assert delivered_bytes == len(expected.encode("utf-8"))
        assert omitted_bytes == 0
        assert result.pending_bytes == 0
        assert result.exit_code == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_cancelling_reused_execute_recovers_session(tmp_path):
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
    task = asyncio.create_task(
        manager.execute(
            "sleep 30",
            session_id=first.session_id,
            shell="/bin/sh",
            cwd=tmp_path,
            env=os.environ.copy(),
            tty=True,
            persistent=True,
            timeout=60,
            yield_time=30,
            max_output_bytes=1024,
        ),
    )
    # Wait until this task owns a running command before cancelling it.
    # pylint: disable=protected-access
    session = manager._sessions[first.session_id]
    for _ in range(100):
        if session.state.value == "running":
            break
        await asyncio.sleep(0.01)
    # pylint: enable=protected-access
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        follow_up = await manager.execute(
            "printf recovered",
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
        assert follow_up.output == "recovered"
        assert follow_up.exit_code == 0
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY behavior")
async def test_cancelling_new_execute_removes_session(tmp_path):
    manager = TerminalSessionManager(tmp_path)
    task = asyncio.create_task(
        manager.execute(
            "sleep 30",
            session_id=None,
            shell="/bin/sh",
            cwd=tmp_path,
            env=os.environ.copy(),
            tty=True,
            persistent=True,
            timeout=60,
            yield_time=30,
            max_output_bytes=1024,
        ),
    )
    for _ in range(100):
        if manager.active_sessions == 1:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.active_sessions == 0
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
async def test_ctrl_c_falls_back_when_pty_etx_is_ignored(
    tmp_path,
    monkeypatch,
):
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
    # Reproduce Linux runners where the PTY accepts ETX but has no foreground
    # process group to receive the terminal-generated SIGINT.
    # pylint: disable=protected-access
    session = manager._sessions[first.session_id]
    original_write = session.backend.write

    async def ignore_etx(data: bytes) -> None:
        if data != b"\x03":
            await original_write(data)

    monkeypatch.setattr(session.backend, "write", ignore_etx)
    # pylint: enable=protected-access
    try:
        interrupted = await manager.interact(
            first.session_id,
            "\x03",
            yield_time=2,
            max_output_bytes=1024,
            terminate=False,
        )
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
    # Exercise the expiry callback race directly; no public API exposes this
    # scheduler boundary.
    # pylint: disable=protected-access
    session = manager._sessions[first.session_id]
    manager._cancel_expiry(first.session_id)
    manager._expiry_due(
        first.session_id,
        session.last_activity,
    )
    # pylint: enable=protected-access

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
