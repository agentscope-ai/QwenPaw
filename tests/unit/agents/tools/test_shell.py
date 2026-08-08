# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tools.shell.

Covers:
- _collapse_embedded_newlines
- _sanitize_win_cmd
- _read_temp_file
- _read_output_snapshot
- _open_temp_output
- _open_windows_temp_output
- _shell_basename
- _is_powershell / _is_cmd
- _extract_powershell_command
- smart_decode
- execute_shell_command (mocked subprocess)
"""

# pylint: disable=protected-access,unused-argument

import os
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.agents.tools.shell import (
    _cancel_stderr_message,
    _collapse_embedded_newlines,
    _execute_in_sandbox,
    _execute_posix_host,
    _execute_subprocess_sync,
    _execute_windows_host,
    _extract_powershell_command,
    _is_cmd,
    _is_dangerous_self_kill,
    _is_powershell,
    _PosixTempOutputs,
    _open_temp_output,
    _open_windows_temp_output,
    _read_temp_file,
    _read_output_snapshot,
    _read_temp_output,
    _sanitize_win_cmd,
    _shell_basename,
    smart_decode,
)
from qwenpaw.sandbox import (
    ExecutionResult,
    MountSpec,
    SandboxConfig,
    SandboxMode,
)

# ---------------------------------------------------------------------------
# _shell_basename
# ---------------------------------------------------------------------------


class TestShellBasename:
    """Tests for _shell_basename."""

    def test_unix_path(self):
        assert _shell_basename("/usr/bin/bash") == "bash"

    def test_windows_path(self):
        assert _shell_basename("C:\\Windows\\cmd.exe") == "cmd.exe"

    def test_powershell_path(self):
        assert (
            _shell_basename(
                "/usr/local/bin/pwsh",
            )
            == "pwsh"
        )

    def test_lowercase(self):
        assert _shell_basename("/bin/BASH") == "bash"


# ---------------------------------------------------------------------------
# _is_powershell / _is_cmd
# ---------------------------------------------------------------------------


class TestIsPowershell:
    """Tests for _is_powershell."""

    @pytest.mark.parametrize(
        "exe",
        ["powershell", "powershell.exe", "pwsh", "pwsh.exe"],
    )
    def test_powershell_variants(self, exe):
        assert _is_powershell(exe) is True

    def test_non_powershell(self):
        assert _is_powershell("/bin/bash") is False

    def test_cmd_is_not_powershell(self):
        assert _is_powershell("cmd") is False


class TestIsCmd:
    """Tests for _is_cmd."""

    @pytest.mark.parametrize("exe", ["cmd", "cmd.exe"])
    def test_cmd_variants(self, exe):
        assert _is_cmd(exe) is True

    def test_non_cmd(self):
        assert _is_cmd("/bin/bash") is False


# ---------------------------------------------------------------------------
# _collapse_embedded_newlines
# ---------------------------------------------------------------------------


class TestCollapseEmbeddedNewlines:
    """Tests for _collapse_embedded_newlines."""

    def test_no_newlines_unchanged(self):
        command = "echo hello"
        assert (
            _collapse_embedded_newlines(command, "powershell.exe") == command
        )

    @patch("qwenpaw.agents.tools.shell.sys")
    def test_windows_cmd_collapses_all(self, mock_sys):
        mock_sys.platform = "win32"
        result = _collapse_embedded_newlines(
            'echo "hello\r\nworld"',
            r"C:\Windows\System32\cmd.exe",
        )
        assert result == 'echo "hello world"'

    @patch("qwenpaw.agents.tools.shell.sys")
    def test_windows_default_shell_collapses_all(self, mock_sys):
        mock_sys.platform = "win32"
        result = _collapse_embedded_newlines('echo "hello\nworld"')
        assert result == 'echo "hello world"'

    @patch("qwenpaw.agents.tools.shell.sys")
    def test_windows_cmd_preserves_standalone_carriage_return(self, mock_sys):
        mock_sys.platform = "win32"
        result = _collapse_embedded_newlines(
            "echo hello\rworld",
            r"C:\Windows\System32\cmd.exe",
        )
        assert result == "echo hello\rworld"

    @pytest.mark.parametrize("shell", ["powershell.exe", "pwsh.exe"])
    @pytest.mark.parametrize("newline", ["\n", "\r\n"])
    @patch("qwenpaw.agents.tools.shell.sys")
    def test_windows_powershell_preserves_here_string(
        self,
        mock_sys,
        newline,
        shell,
    ):
        mock_sys.platform = "win32"
        command = (
            f'$content = @"{newline}hello{newline}'
            f'world{newline}"@{newline}$content'
        )
        assert _collapse_embedded_newlines(command, shell) == command

    @patch("qwenpaw.agents.tools.shell.sys")
    def test_unix_preserves_quoted_newlines(self, mock_sys):
        mock_sys.platform = "linux"
        command = 'echo "hello\nworld"'
        assert _collapse_embedded_newlines(command, "/bin/bash") == command

    @pytest.mark.parametrize(
        "command",
        [
            "echo A\necho B",
            "cd /repo &&\npwd",
            "printf foo |\ngrep foo",
            "for item in a b; do\n  echo $item\ndone",
            "cat <<'EOF'\nhello\nEOF",
            "echo A\n\necho B",
        ],
    )
    @patch("qwenpaw.agents.tools.shell.sys")
    def test_unix_preserves_shell_program(self, mock_sys, command):
        mock_sys.platform = "linux"
        assert _collapse_embedded_newlines(command, "/bin/bash") == command


# ---------------------------------------------------------------------------
# _sanitize_win_cmd
# ---------------------------------------------------------------------------


class TestSanitizeWinCmd:
    """Tests for _sanitize_win_cmd."""

    def test_no_escaped_quotes(self):
        assert _sanitize_win_cmd("echo hello") == "echo hello"

    def test_all_escaped_quotes_stripped(self):
        # Every " is preceded by \ — double-escape artefact
        result = _sanitize_win_cmd('echo \\"hello\\"')
        assert result == 'echo "hello"'

    def test_mixed_quotes_not_stripped(self):
        # Mix of escaped and unescaped — don't strip
        cmd = 'echo \\"hello" world'
        assert _sanitize_win_cmd(cmd) == cmd


# ---------------------------------------------------------------------------
# _read_temp_file
# ---------------------------------------------------------------------------


class TestReadTempFile:
    """Tests for _read_temp_file."""

    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("hello world", encoding="utf-8")
        result = _read_temp_file(str(f))
        assert result == "hello world"

    def test_read_nonexistent_file(self):
        result = _read_temp_file("/nonexistent/file.txt")
        assert result == ""

    def test_read_utf8_bytes(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_bytes("你好".encode("utf-8"))
        result = _read_temp_file(str(f))
        assert "你好" in result

    def test_truncates_large_snapshot_with_notice(self, tmp_path):
        output = tmp_path / "large.txt"
        output.write_bytes(b"abcdefghij")

        result = _read_temp_file(str(output), max_bytes=4)

        assert result.startswith("abcd\n")
        assert "Output truncated" in result
        assert "10-byte snapshot" in result


class TestReadOutputSnapshot:
    """Tests for fixed-size output snapshot reads."""

    def test_reads_only_recorded_bounded_size(self):
        output = MagicMock()
        output.fileno.return_value = 123
        output.read.return_value = b"abcd"
        stat_result = MagicMock(st_size=10)

        with patch(
            "qwenpaw.agents.tools.shell.os.fstat",
            return_value=stat_result,
        ):
            result = _read_output_snapshot(output, max_bytes=4)

        output.seek.assert_called_once_with(0)
        output.read.assert_called_once_with(4)
        assert result.startswith("abcd\n")
        assert "Output truncated" in result


class TestOpenTempOutput:
    """Tests for _open_temp_output."""

    def test_fdopen_failure_closes_fd_and_unlinks_path(self, tmp_path):
        fd, path = tempfile.mkstemp(dir=tmp_path)

        try:
            with (
                patch(
                    "qwenpaw.agents.tools.shell.tempfile.mkstemp",
                    return_value=(fd, path),
                ),
                patch(
                    "qwenpaw.agents.tools.shell.os.fdopen",
                    side_effect=OSError("fdopen failed"),
                ),
                patch(
                    "qwenpaw.agents.tools.shell.os.close",
                    wraps=os.close,
                ) as close_fd,
            ):
                with pytest.raises(OSError, match="fdopen failed"):
                    _open_temp_output("qwenpaw_out_")

            close_fd.assert_called_once_with(fd)
            assert not Path(path).exists()
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            Path(path).unlink(missing_ok=True)


class TestOpenWindowsTempOutput:
    """Tests for Windows delete-on-close temporary output handles."""

    def test_uses_delete_sharing_and_independent_reader(self):
        writer = MagicMock()
        writer.name = r"C:\Temp\qwenpaw_out_test"
        reader = MagicMock()

        with (
            patch(
                "qwenpaw.agents.tools.shell.tempfile.NamedTemporaryFile",
                return_value=writer,
            ) as named_temp,
            patch(
                "qwenpaw.agents.tools.shell.os.O_TEMPORARY",
                0x40,
                create=True,
            ),
            patch(
                "qwenpaw.agents.tools.shell.os.O_BINARY",
                0x80,
                create=True,
            ),
            patch(
                "qwenpaw.agents.tools.shell.os.open",
                return_value=123,
            ) as open_file,
            patch(
                "qwenpaw.agents.tools.shell.os.fdopen",
                return_value=reader,
            ) as fdopen,
        ):
            result = _open_windows_temp_output("qwenpaw_out_")

        assert result == (writer, reader)
        named_temp.assert_called_once_with(
            mode="w+b",
            prefix="qwenpaw_out_",
            delete=True,
        )
        open_file.assert_called_once_with(
            writer.name,
            os.O_RDONLY | 0x40 | 0x80,
        )
        fdopen.assert_called_once_with(123, "rb")

    def test_reader_open_failure_closes_writer_and_raw_fd(self):
        writer = MagicMock()
        writer.name = r"C:\Temp\qwenpaw_out_test"

        with (
            patch(
                "qwenpaw.agents.tools.shell.tempfile.NamedTemporaryFile",
                return_value=writer,
            ),
            patch(
                "qwenpaw.agents.tools.shell.os.open",
                return_value=123,
            ),
            patch(
                "qwenpaw.agents.tools.shell.os.fdopen",
                side_effect=OSError("fdopen failed"),
            ),
            patch("qwenpaw.agents.tools.shell.os.close") as close_fd,
        ):
            with pytest.raises(OSError, match="fdopen failed"):
                _open_windows_temp_output("qwenpaw_out_")

        close_fd.assert_called_once_with(123)
        writer.close.assert_called_once_with()

    def test_read_uses_independent_file_position(self):
        reader = MagicMock()
        reader.fileno.return_value = 123
        reader.read.return_value = "你好".encode("utf-8")

        with patch(
            "qwenpaw.agents.tools.shell.os.fstat",
            return_value=MagicMock(st_size=6),
        ):
            result = _read_temp_output(reader)

        assert result == "你好"
        reader.seek.assert_called_once_with(0)
        reader.read.assert_called_once_with(6)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows handle inheritance semantics under test",
)
def test_windows_background_handles_are_eventually_deleted(
    tmp_path,
    monkeypatch,
):
    """Delete-on-close removes output after a background descendant exits."""
    import time

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    release_path = tmp_path / "release.signal"
    child_script_path = tmp_path / "wait_for_release.py"
    child_script_path.write_text(
        "from pathlib import Path\n"
        "import time\n"
        "\n"
        "release_path = Path('release.signal')\n"
        "while not release_path.exists():\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    escaped_python = sys.executable.replace("'", "''")
    escaped_working_dir = str(tmp_path).replace("'", "''")
    command = (
        f"$child = Start-Process -FilePath '{escaped_python}' "
        "-ArgumentList 'wait_for_release.py' "
        f"-WorkingDirectory '{escaped_working_dir}' "
        "-NoNewWindow -PassThru; Write-Output done"
    )

    returncode, stdout, stderr = _execute_subprocess_sync(
        command,
        str(tmp_path),
        timeout=15.0,
        env=os.environ.copy(),
        shell_executable="powershell.exe",
    )
    pending_paths = list(tmp_path.glob("qwenpaw_*"))
    release_path.touch()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not list(tmp_path.glob("qwenpaw_*")):
            break
        time.sleep(0.1)

    details = f"stdout={stdout!r}, stderr={stderr!r}"
    assert returncode == 0, details
    assert stdout == "done", details
    assert stderr == "", details
    assert pending_paths, (
        f"Background process did not retain temporary output handles; "
        f"{details}"
    )
    assert not list(tmp_path.glob("qwenpaw_*"))


# ---------------------------------------------------------------------------
# _extract_powershell_command
# ---------------------------------------------------------------------------


class TestExtractPowershellCommand:
    """Tests for _extract_powershell_command."""

    def test_powershell_command(self):
        ps_exe, inner = _extract_powershell_command(
            'powershell -Command "Get-Process"',
        )
        assert ps_exe == "powershell"
        assert inner == "Get-Process"

    def test_pwsh_command(self):
        ps_exe, _ = _extract_powershell_command(
            'pwsh -Command "Get-Process"',
        )
        assert ps_exe == "pwsh"

    def test_powershell_with_flags(self):
        ps_exe, inner = _extract_powershell_command(
            "powershell -NoProfile -NonInteractive -Command Get-Process",
        )
        assert ps_exe == "powershell"
        assert inner == "Get-Process"

    def test_non_powershell(self):
        ps_exe, inner = _extract_powershell_command("echo hello")
        assert ps_exe is None
        assert inner == "echo hello"

    def test_pwsh_exe(self):
        ps_exe, _ = _extract_powershell_command(
            "pwsh.exe -Command test",
        )
        assert ps_exe == "pwsh.exe"

    def test_execution_policy_flag(self):
        ps_exe, inner = _extract_powershell_command(
            "powershell -ExecutionPolicy Bypass -Command echo hi",
        )
        assert ps_exe == "powershell"
        assert inner == "echo hi"


# ---------------------------------------------------------------------------
# smart_decode
# ---------------------------------------------------------------------------


class TestSmartDecode:
    """Tests for smart_decode."""

    def test_utf8_bytes(self):
        result = smart_decode("hello".encode("utf-8"))
        assert result == "hello"

    def test_strips_trailing_newlines(self):
        result = smart_decode("hello\n\n".encode("utf-8"))
        assert result == "hello"

    def test_strips_windows_newline_and_preserves_internal_crlf(self):
        result = smart_decode("first\r\nsecond\r\n".encode("utf-8"))
        assert result == "first\r\nsecond"

    def test_non_utf8_fallback(self):
        # Bytes that are invalid UTF-8 should fall back to
        # locale encoding with error replacement
        data = b"\xff\xfe"  # BOM for UTF-16-LE, invalid UTF-8
        result = smart_decode(data)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _is_dangerous_self_kill
# ---------------------------------------------------------------------------


class TestIsDangerousSelfKill:
    """Tests for _is_dangerous_self_kill."""

    def test_taskkill_by_image_name_python(self):
        assert _is_dangerous_self_kill("taskkill /F /IM python.exe")

    def test_taskkill_by_image_name_pythonw(self):
        assert _is_dangerous_self_kill("taskkill /F /IM pythonw.exe")

    def test_taskkill_by_image_name_cmd(self):
        assert _is_dangerous_self_kill("taskkill /F /IM cmd.exe")

    def test_taskkill_by_image_name_powershell(self):
        assert _is_dangerous_self_kill("taskkill /F /IM powershell.exe")

    def test_taskkill_by_image_name_pwsh(self):
        assert _is_dangerous_self_kill("taskkill /F /IM pwsh.exe")

    def test_taskkill_by_image_name_conhost(self):
        assert _is_dangerous_self_kill("taskkill /F /IM conhost.exe")

    def test_taskkill_by_image_name_without_exe(self):
        assert _is_dangerous_self_kill("taskkill /F /IM python")

    def test_taskkill_by_pid_self(self):
        assert _is_dangerous_self_kill(f"taskkill /F /PID {os.getpid()}")

    def test_taskkill_by_pid_parent(self):
        if hasattr(os, "getppid"):
            assert _is_dangerous_self_kill(
                f"taskkill /F /PID {os.getppid()}",
            )

    def test_taskkill_by_pid_other_is_safe(self):
        assert not _is_dangerous_self_kill("taskkill /F /PID 99999")

    def test_kill_unix_pid_self(self):
        assert _is_dangerous_self_kill(f"kill -9 {os.getpid()}")

    def test_kill_unix_pid_other_is_safe(self):
        assert not _is_dangerous_self_kill("kill -9 99999")

    def test_kill_shell_var_dollar_dollar(self):
        assert _is_dangerous_self_kill("kill -9 $$")

    def test_kill_shell_var_ppid(self):
        assert _is_dangerous_self_kill("kill $PPID")

    def test_kill_shell_var_pid(self):
        assert _is_dangerous_self_kill("kill $PID")

    def test_false_positive_command_contains_cmd(self):
        """'command' contains 'cmd' but should not be blocked."""
        assert not _is_dangerous_self_kill("echo 'run a command'")

    def test_false_positive_echo_kill_python(self):
        """echo with 'kill python' in text should not be blocked."""
        assert not _is_dangerous_self_kill(
            'echo "do not kill python"',
        )

    def test_false_positive_cat_file(self):
        """Reading a file named kill_list_python.txt should not be blocked."""
        assert not _is_dangerous_self_kill("cat kill_list_python.txt")

    def test_safe_command(self):
        assert not _is_dangerous_self_kill("echo hello")

    def test_stop_process_by_name(self):
        assert _is_dangerous_self_kill("Stop-Process -Name python")


# ---------------------------------------------------------------------------
# _execute_posix_host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_captures_regular_file_output(tmp_path):
    """POSIX host execution waits on the shell and reads temp files."""
    import asyncio

    proc = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    proc.pid = 12345

    async def fake_create_subprocess_exec(*_args, **kwargs):
        kwargs["stdout"].write(b"hello\n")
        kwargs["stdout"].flush()
        kwargs["stderr"].write(b"warning\n")
        kwargs["stderr"].flush()
        return proc

    with (
        patch(
            "qwenpaw.agents.tools.shell.asyncio.create_subprocess_exec",
            side_effect=fake_create_subprocess_exec,
        ) as create_process,
        patch(
            "qwenpaw.agents.tools.shell.tempfile.tempdir",
            str(tmp_path),
        ),
    ):
        returncode, stdout, stderr = await _execute_posix_host(
            "echo hello",
            str(tmp_path),
            5.0,
            os.environ.copy(),
            "/bin/sh",
        )

    assert returncode == 0
    assert stdout == "hello"
    assert stderr == "warning"
    proc.wait.assert_awaited_once()
    assert create_process.call_args.args == ("/bin/sh", "-c", "echo hello")
    kwargs = create_process.call_args.kwargs
    assert kwargs["stdout"] != asyncio.subprocess.PIPE
    assert kwargs["stderr"] != asyncio.subprocess.PIPE
    assert kwargs["cwd"] == str(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_background_child_does_not_delay(tmp_path):
    """A background child retaining output descriptors must not block."""
    returncode, stdout, stderr = await _execute_posix_host(
        "sleep 2 &\nprintf done",
        str(tmp_path),
        0.5,
        os.environ.copy(),
        "/bin/sh",
    )

    assert returncode == 0
    assert stdout == "done"
    assert stderr == ""


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_bounds_continuously_growing_output(
    tmp_path,
    monkeypatch,
):
    """A background writer cannot make snapshot collection chase EOF."""
    import asyncio
    import time

    max_bytes = 4096
    monkeypatch.setattr(
        "qwenpaw.agents.tools.shell._SHELL_OUTPUT_MAX_BYTES",
        max_bytes,
    )
    pid_path = tmp_path / "background.pid"
    ready_path = tmp_path / "writer.ready"
    writer_code = (
        "import os,sys,time\n"
        "chunk=b'x'*4096\n"
        "os.write(1,chunk)\n"
        "open(sys.argv[1],'wb').close()\n"
        "while True:\n"
        " os.write(1,chunk)\n"
        " time.sleep(0.005)"
    )
    command = (
        f"{shlex.quote(sys.executable)} -c {shlex.quote(writer_code)} "
        f"{shlex.quote(str(ready_path))} & "
        f"echo $! > {shlex.quote(str(pid_path))}; "
        f"while [ ! -e {shlex.quote(str(ready_path))} ]; "
        f"do sleep 0.01; done; printf done"
    )

    started = time.monotonic()
    background_pid = None
    try:
        returncode, stdout, stderr = await asyncio.wait_for(
            _execute_posix_host(
                command,
                str(tmp_path),
                2.0,
                os.environ.copy(),
                "/bin/sh",
            ),
            timeout=3.0,
        )
        if pid_path.exists():
            background_pid = int(pid_path.read_text(encoding="utf-8"))
    finally:
        if background_pid is None and pid_path.exists():
            background_pid = int(pid_path.read_text(encoding="utf-8"))
        if background_pid is not None:
            try:
                os.kill(background_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert returncode == 0
    assert "Output truncated" in stdout
    assert len(stdout.encode("utf-8")) < max_bytes + 256
    assert stderr == ""
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_slow_temp_io_does_not_block_loop(
    tmp_path,
):
    """Slow create/unlink operations must run outside the event loop."""
    import asyncio
    import time

    real_mkstemp = tempfile.mkstemp
    real_unlink = os.unlink
    ticker_done = asyncio.Event()
    ticks = 0

    def slow_mkstemp(*args, **kwargs):
        time.sleep(0.05)
        kwargs["dir"] = tmp_path
        return real_mkstemp(*args, **kwargs)

    def slow_unlink(path):
        time.sleep(0.05)
        return real_unlink(path)

    async def ticker():
        nonlocal ticks
        while not ticker_done.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    ticker_task = asyncio.create_task(ticker())
    try:
        with (
            patch(
                "qwenpaw.agents.tools.shell.tempfile.mkstemp",
                side_effect=slow_mkstemp,
            ),
            patch(
                "qwenpaw.agents.tools.shell.os.unlink",
                side_effect=slow_unlink,
            ),
        ):
            returncode, stdout, stderr = await _execute_posix_host(
                "printf ok",
                str(tmp_path),
                2.0,
                os.environ.copy(),
                "/bin/sh",
            )
    finally:
        ticker_done.set()
        await ticker_task

    assert returncode == 0
    assert stdout == "ok"
    assert stderr == ""
    assert ticks >= 10


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_cancel_during_snapshot_cleans_up(
    tmp_path,
):
    """Cancellation waits for bounded I/O, then removes temporary files."""
    import asyncio
    import threading

    read_started = threading.Event()
    release_read = threading.Event()
    real_read_snapshot = _PosixTempOutputs.read_snapshot

    def slow_read_snapshot(outputs, max_bytes):
        read_started.set()
        release_read.wait(timeout=2.0)
        return real_read_snapshot(outputs, max_bytes)

    with (
        patch(
            "qwenpaw.agents.tools.shell.tempfile.tempdir",
            str(tmp_path),
        ),
        patch.object(
            _PosixTempOutputs,
            "read_snapshot",
            autospec=True,
            side_effect=slow_read_snapshot,
        ),
    ):
        task = asyncio.create_task(
            _execute_posix_host(
                "printf partial",
                str(tmp_path),
                2.0,
                os.environ.copy(),
                "/bin/sh",
            ),
        )
        for _ in range(200):
            if read_started.is_set():
                break
            await asyncio.sleep(0.005)
        assert read_started.is_set()

        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release_read.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert not list(tmp_path.glob("qwenpaw_*"))


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_context_cancel_during_snapshot(
    tmp_path,
):
    """Context cancellation is observed during bounded output collection."""
    import asyncio
    import threading

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import CancelReason, ToolCallContext

    read_started = threading.Event()
    release_read = threading.Event()
    real_read_snapshot = _PosixTempOutputs.read_snapshot

    def slow_read_snapshot(outputs, max_bytes):
        read_started.set()
        release_read.wait(timeout=2.0)
        return real_read_snapshot(outputs, max_bytes)

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-posix-snapshot-cancel",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:
        with (
            patch(
                "qwenpaw.agents.tools.shell.tempfile.tempdir",
                str(tmp_path),
            ),
            patch.object(
                _PosixTempOutputs,
                "read_snapshot",
                autospec=True,
                side_effect=slow_read_snapshot,
            ),
        ):
            task = asyncio.create_task(
                _execute_posix_host(
                    "printf partial",
                    str(tmp_path),
                    2.0,
                    os.environ.copy(),
                    "/bin/sh",
                ),
            )
            for _ in range(200):
                if read_started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert read_started.is_set()

            ctx.cancel_reason = CancelReason.USER
            ctx.cancel_event.set()
            await asyncio.sleep(0.02)
            assert not task.done()
            release_read.set()
            returncode, stdout, stderr = await task
    finally:
        reset_call_context(token)

    assert returncode == -1
    assert stdout == "partial"
    assert "cancelled by the user" in stderr
    assert not list(tmp_path.glob("qwenpaw_*"))


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_snapshot_uses_remaining_timeout(
    tmp_path,
):
    """Direct calls retain one deadline across wait and output collection."""
    import threading

    release_read = threading.Event()
    real_read_snapshot = _PosixTempOutputs.read_snapshot

    def slow_read_snapshot(outputs, max_bytes):
        release_read.wait(timeout=0.3)
        return real_read_snapshot(outputs, max_bytes)

    with (
        patch(
            "qwenpaw.agents.tools.shell.tempfile.tempdir",
            str(tmp_path),
        ),
        patch.object(
            _PosixTempOutputs,
            "read_snapshot",
            autospec=True,
            side_effect=slow_read_snapshot,
        ),
    ):
        returncode, stdout, stderr = await _execute_posix_host(
            "printf partial",
            str(tmp_path),
            0.2,
            os.environ.copy(),
            "/bin/sh",
        )

    assert returncode == -1
    assert stdout == "partial"
    assert "TimeoutError" in stderr
    assert not list(tmp_path.glob("qwenpaw_*"))


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_snapshot_drain_has_grace_timeout(
    tmp_path,
    monkeypatch,
):
    """Hung snapshot I/O is detached after the bounded drain window."""
    import asyncio
    import threading
    import time

    read_started = threading.Event()
    release_read = threading.Event()
    real_read_snapshot = _PosixTempOutputs.read_snapshot

    def blocked_read_snapshot(outputs, max_bytes):
        read_started.set()
        release_read.wait(timeout=2.0)
        return real_read_snapshot(outputs, max_bytes)

    monkeypatch.setattr(
        "qwenpaw.agents.tools.shell._SHELL_OUTPUT_DRAIN_GRACE_SECS",
        0.02,
    )
    started = time.monotonic()
    try:
        with (
            patch(
                "qwenpaw.agents.tools.shell.tempfile.tempdir",
                str(tmp_path),
            ),
            patch.object(
                _PosixTempOutputs,
                "read_snapshot",
                autospec=True,
                side_effect=blocked_read_snapshot,
            ),
        ):
            returncode, stdout, stderr = await _execute_posix_host(
                "printf partial",
                str(tmp_path),
                0.2,
                os.environ.copy(),
                "/bin/sh",
            )
    finally:
        release_read.set()

    assert read_started.is_set()
    assert time.monotonic() - started < 1.0
    assert returncode == -1
    assert stdout == ""
    assert "Output collection omitted" in stderr
    assert "TimeoutError" in stderr
    assert not list(tmp_path.glob("qwenpaw_*"))
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX host subprocess path under test",
)
async def test_execute_posix_host_timeout_preserves_partial_output(tmp_path):
    """Timeout cleanup keeps output emitted before the process is killed."""
    returncode, stdout, stderr = await _execute_posix_host(
        "printf partial-out; printf partial-err >&2; sleep 5",
        str(tmp_path),
        0.2,
        os.environ.copy(),
        "/bin/sh",
    )

    assert returncode == -1
    assert stdout == "partial-out"
    assert stderr.startswith("partial-err\n")
    assert "TimeoutError" in stderr


# ---------------------------------------------------------------------------
# execute_shell_command (mocked)
# ---------------------------------------------------------------------------


class TestExecuteShellCommand:
    """Tests for execute_shell_command with mocked subprocess."""

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_timeout")
    @patch("qwenpaw.agents.tools.shell.get_current_workspace_dir")
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_executable")
    async def test_simple_command_success(
        self,
        mock_shell_exe,
        mock_workspace,
        mock_timeout,
    ):
        mock_shell_exe.return_value = None
        mock_workspace.return_value = None
        mock_timeout.return_value = None

        with (
            patch(
                "qwenpaw.agents.tools.shell.sys.platform",
                "linux",
            ),
            patch(
                "qwenpaw.agents.tools.shell._execute_posix_host",
                AsyncMock(return_value=(0, "hello\n", "")),
            ),
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            result = await execute_shell_command("echo hello")
            assert result.content is not None
            text = result.content[0].text
            assert "hello" in text

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_timeout")
    @patch("qwenpaw.agents.tools.shell.get_current_workspace_dir")
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_executable")
    async def test_unix_multiline_command_reaches_shell_unchanged(
        self,
        mock_shell_exe,
        mock_workspace,
        mock_timeout,
    ):
        mock_shell_exe.return_value = "/bin/sh"
        mock_workspace.return_value = None
        mock_timeout.return_value = None
        command = "echo A\necho B"

        with (
            patch("qwenpaw.agents.tools.shell.sys.platform", "linux"),
            patch(
                "qwenpaw.agents.tools.shell._execute_posix_host",
                AsyncMock(return_value=(0, "A\nB", "")),
            ) as execute_posix,
        ):
            from qwenpaw.agents.tools.shell import execute_shell_command

            result = await execute_shell_command(command)

        assert result.content[0].text == "A\nB"
        assert execute_posix.call_args.args[0] == command

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_timeout")
    @patch("qwenpaw.agents.tools.shell.get_current_workspace_dir")
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_executable")
    async def test_command_failure(
        self,
        mock_shell_exe,
        mock_workspace,
        mock_timeout,
    ):
        mock_shell_exe.return_value = None
        mock_workspace.return_value = None
        mock_timeout.return_value = None

        with (
            patch(
                "qwenpaw.agents.tools.shell.sys.platform",
                "linux",
            ),
            patch(
                "qwenpaw.agents.tools.shell._execute_posix_host",
                AsyncMock(return_value=(1, "", "error msg\n")),
            ),
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            result = await execute_shell_command("false")
            text = result.content[0].text
            assert "failed" in text.lower() or "error" in text.lower()

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_timeout")
    @patch("qwenpaw.agents.tools.shell.get_current_workspace_dir")
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_executable")
    async def test_empty_command(
        self,
        mock_shell_exe,
        mock_workspace,
        mock_timeout,
    ):
        mock_shell_exe.return_value = None
        mock_workspace.return_value = None
        mock_timeout.return_value = None

        with (
            patch(
                "qwenpaw.agents.tools.shell.sys.platform",
                "linux",
            ),
            patch(
                "qwenpaw.agents.tools.shell._execute_posix_host",
                AsyncMock(return_value=(0, "", "")),
            ),
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            result = await execute_shell_command("")
            text = result.content[0].text
            assert "successfully" in text.lower()

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_timeout")
    @patch("qwenpaw.agents.tools.shell.get_current_workspace_dir")
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_executable")
    async def test_timeout_string_converted(
        self,
        mock_shell_exe,
        mock_workspace,
        mock_timeout,
    ):
        mock_shell_exe.return_value = None
        mock_workspace.return_value = None
        mock_timeout.return_value = None

        with (
            patch(
                "qwenpaw.agents.tools.shell.sys.platform",
                "linux",
            ),
            patch(
                "qwenpaw.agents.tools.shell._execute_posix_host",
                AsyncMock(return_value=(0, "ok", "")),
            ),
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            # timeout as string "30" should be converted to float
            result = await execute_shell_command("echo ok", timeout="30")
            assert result.content is not None

    @pytest.mark.asyncio
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_timeout")
    @patch("qwenpaw.agents.tools.shell.get_current_workspace_dir")
    @patch("qwenpaw.agents.tools.shell.get_current_shell_command_executable")
    async def test_invalid_timeout_defaults(
        self,
        mock_shell_exe,
        mock_workspace,
        mock_timeout,
    ):
        mock_shell_exe.return_value = None
        mock_workspace.return_value = None
        mock_timeout.return_value = None

        with (
            patch(
                "qwenpaw.agents.tools.shell.sys.platform",
                "linux",
            ),
            patch(
                "qwenpaw.agents.tools.shell._execute_posix_host",
                AsyncMock(return_value=(0, "ok", "")),
            ),
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            # Invalid timeout string falls back to 60.0 default
            result = await execute_shell_command(
                "echo ok",
                timeout="invalid",
            )
            assert result.content is not None

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="NoneSandbox currently requires a POSIX shell",
    )
    async def test_sandbox_path_starts_with_running_python_bin(
        self,
        monkeypatch,
        tmp_path,
    ):
        from qwenpaw.agents.tools.shell import execute_shell_command

        system_bin = tmp_path / "system-bin"
        system_bin.mkdir()
        monkeypatch.setenv("PATH", str(system_bin))
        if sys.platform != "win32":
            monkeypatch.setenv("SHELL", "/bin/sh")

        script = "import os; print(os.environ.get('PATH', ''))"
        args = [sys.executable, "-c", script]
        command = (
            subprocess.list2cmdline(args)
            if sys.platform == "win32"
            else shlex.join(args)
        )
        config = SandboxConfig(
            mode=SandboxMode.NONE,
            workspace_dir=str(tmp_path),
            mounts=[MountSpec(path=str(tmp_path), writable=True)],
        )

        result = await execute_shell_command(
            command,
            cwd=tmp_path,
            sandbox_config=config,
        )

        path_entries = result.content[0].text.strip().split(os.pathsep)
        assert Path(path_entries[0]) == Path(sys.executable).parent
        assert config.env_vars == {}
        assert config.timeout_seconds == 30

    @pytest.mark.asyncio
    async def test_sandbox_uses_explicit_path_without_mutating_config(
        self,
        tmp_path,
    ):
        configured_path = os.pathsep.join(["custom", "bin"])
        config = SandboxConfig(
            mode=SandboxMode.NONE,
            workspace_dir=str(tmp_path),
            env_vars={"PATH": configured_path, "MASKED_SECRET": ""},
        )
        sandbox = AsyncMock()
        sandbox.execute.return_value = ExecutionResult(0, "ok", "")
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=sandbox)
        context_manager.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "qwenpaw.sandbox.create_sandbox",
            return_value=context_manager,
        ) as create_sandbox:
            await _execute_in_sandbox(
                "echo ok",
                config,
                12.9,
                str(tmp_path),
                {"PATH": os.pathsep.join(["venv", "system"])},
            )

        effective_config = create_sandbox.call_args.args[0]
        assert effective_config.env_vars == {
            "PATH": configured_path,
            "MASKED_SECRET": "",
        }
        assert effective_config.timeout_seconds == 12
        assert config.env_vars == {
            "PATH": configured_path,
            "MASKED_SECRET": "",
        }
        assert config.timeout_seconds == 30


@pytest.mark.asyncio
async def test_sandbox_under_ctx_does_not_freeze_original_timeout(tmp_path):
    """With ToolCallContext, sandbox wait must not freeze the tool timeout."""
    import asyncio

    from qwenpaw.tool_calls import (
        COORDINATOR_OWNED_EXEC_TIMEOUT_SECS,
        reset_call_context,
        set_call_context,
    )
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-sandbox-extend",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=loop.time() + 30,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecutionResult(0, "ok", "")
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=sandbox)
    context_manager.__aexit__ = AsyncMock(return_value=None)
    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
    )

    try:
        with patch(
            "qwenpaw.sandbox.create_sandbox",
            return_value=context_manager,
        ) as create_sandbox:
            await _execute_in_sandbox(
                "echo ok",
                config,
                12.0,
                str(tmp_path),
                {"PATH": "/bin"},
            )
        effective_config = create_sandbox.call_args.args[0]
        assert (
            effective_config.timeout_seconds
            == COORDINATOR_OWNED_EXEC_TIMEOUT_SECS
        )
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_sandbox_extend_kill_survives_then_cancel_stops(tmp_path):
    """extend_kill keeps sandbox past original timeout; cancel calls stop()."""
    import asyncio
    from dataclasses import dataclass, field
    from typing import Any, AsyncGenerator

    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse

    from qwenpaw.sandbox.local_sandbox import NoneSandbox
    from qwenpaw.tool_calls import ToolCoordinator

    @dataclass
    class _ToolCall:
        id: str = "call-sandbox-ext"
        name: str = "execute_shell_command"
        input: dict[str, Any] = field(default_factory=dict)

    coordinator = ToolCoordinator(offload_on_deadline=False)
    tool_call = _ToolCall()
    started = asyncio.Event()
    release = asyncio.Event()
    stop_mock = AsyncMock()

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        config = SandboxConfig(
            mode=SandboxMode.NONE,
            workspace_dir=str(tmp_path),
            timeout_seconds=60,
        )
        sandbox = NoneSandbox(config)
        proc = MagicMock()
        proc.returncode = None
        proc.pid = 4243

        async def hang_communicate():
            started.set()
            await release.wait()
            return b"survived\n", b""

        proc.communicate = hang_communicate
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=sandbox)
        context_manager.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "qwenpaw.sandbox.create_sandbox",
                return_value=context_manager,
            ),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ),
            patch.object(sandbox, "stop", new=stop_mock),
        ):
            result = await _execute_in_sandbox(
                "sleep 1",
                config,
                0.08,
                str(tmp_path),
                {"PATH": "/bin"},
            )
        yield ToolResponse(
            content=[TextBlock(type="text", text=result.stdout or "")],
            id=tool_call.id,
        )

    async def extend_then_cancel() -> None:
        await started.wait()
        await asyncio.sleep(0.04)
        ok = await coordinator.extend_kill_deadline(
            "call-sandbox-ext",
            seconds=1.0,
        )
        assert ok is True
        # Past original 0.08s — must still be running (not returned yet).
        await asyncio.sleep(0.08)
        assert release.is_set() is False
        assert stop_mock.await_count == 0
        cancelled = await coordinator.cancel("call-sandbox-ext")
        assert cancelled is True
        await asyncio.sleep(0.05)
        stop_mock.assert_awaited()

    ctrl = asyncio.create_task(extend_then_cancel())
    events = await asyncio.wait_for(
        _collect_sandbox_events(
            coordinator.execute(
                tool_call=tool_call,
                next_handler=next_handler,
                session_id="session-sandbox-ext",
                agent_id="agent-1",
                root_session_id="root-1",
            ),
        ),
        timeout=3,
    )
    await ctrl
    # Cancel may surface as interrupted; key assertion is stop().
    assert events
    assert stop_mock.await_count >= 1


async def _collect_sandbox_events(iterator):
    events = []
    async for item in iterator:
        events.append(item)
    return events


@pytest.mark.asyncio
async def test_none_sandbox_execute_cancel_calls_stop(tmp_path):
    """CancelledError in sandbox.execute must call stop()."""
    import asyncio

    from qwenpaw.sandbox.local_sandbox import NoneSandbox

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
        timeout_seconds=60,
    )
    sandbox = NoneSandbox(config)
    proc = MagicMock()
    proc.returncode = None
    proc.pid = 4242

    async def hang_communicate():
        await asyncio.sleep(60)
        return b"", b""

    proc.communicate = hang_communicate
    stop_mock = AsyncMock()

    with (
        patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ),
        patch.object(sandbox, "stop", new=stop_mock),
    ):
        task = asyncio.create_task(
            sandbox.execute("sleep 1", cwd=str(tmp_path)),
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        stop_mock.assert_awaited()


@pytest.mark.asyncio
async def test_sandbox_setup_preserves_offload_remaining_and_arms_kill(
    tmp_path,
):
    """Setup must not collapse offload into the command timeout.

    When command kill (12s) is shorter than the pre-setup offload window
    (30s), arming kill pulls offload back to ``12 * OFFLOAD_TIMEOUT_RATIO``
    so kill stays strictly later — without rewriting offload to the full
    command timeout.
    """
    import asyncio

    from qwenpaw.tool_calls import (
        OFFLOAD_TIMEOUT_RATIO,
        reset_call_context,
        set_call_context,
    )
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    now = loop.time()
    offload_remaining = 30.0
    offload_at = now + offload_remaining
    command_timeout = 12.0
    ctx = ToolCallContext(
        tool_call_id="tc-sandbox-ddl",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=offload_at,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecutionResult(0, "ok", "")
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=sandbox)
    context_manager.__aexit__ = AsyncMock(return_value=None)

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
    )

    try:
        with patch(
            "qwenpaw.sandbox.create_sandbox",
            return_value=context_manager,
        ):
            result = await _execute_in_sandbox(
                "echo ok",
                config,
                command_timeout,
                str(tmp_path),
                {"PATH": "/bin"},
            )
        assert result.exit_code == 0
        assert ctx.kill_deadline is not None
        kill_remaining = ctx.kill_deadline - loop.time()
        assert kill_remaining == pytest.approx(command_timeout, abs=1.0)
        # Short kill pulled offload back; must stay strictly before kill.
        assert ctx.offload_deadline is not None
        offload_left = ctx.offload_deadline - loop.time()
        assert offload_left == pytest.approx(
            command_timeout * OFFLOAD_TIMEOUT_RATIO,
            abs=0.5,
        )
        assert ctx.offload_deadline < ctx.kill_deadline
        assert not ctx.cancel_event.is_set()
        sandbox.execute.assert_awaited_once()
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_sandbox_setup_extension_does_not_leave_kill_armed_early(
    tmp_path,
):
    """kill_deadline must be unset during setup and only armed for execute."""
    import asyncio

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    now = loop.time()
    offload_remaining = 5.0
    offload_at = now + offload_remaining
    ctx = ToolCallContext(
        tool_call_id="tc-sandbox-setup",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=offload_at,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    seen_during_setup = {}

    class _SandboxCM:
        async def __aenter__(self):
            # During setup enter, kill must not already be command-timeout.
            seen_during_setup["kill"] = ctx.kill_deadline
            seen_during_setup["offload"] = ctx.offload_deadline
            sandbox = AsyncMock()
            sandbox.execute.return_value = ExecutionResult(0, "ok", "")
            return sandbox

        async def __aexit__(self, *args):
            return None

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
    )

    try:
        with patch(
            "qwenpaw.sandbox.create_sandbox",
            return_value=_SandboxCM(),
        ):
            await _execute_in_sandbox(
                "echo ok",
                config,
                9.0,
                str(tmp_path),
                {"PATH": "/bin"},
            )
        assert seen_during_setup["kill"] is None
        assert seen_during_setup["offload"] == pytest.approx(
            offload_at + 180.0,
            abs=0.05,
        )
        remaining = ctx.offload_deadline - loop.time()
        assert remaining == pytest.approx(offload_remaining, abs=0.2)
        assert ctx.kill_deadline is not None
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_sandbox_slow_setup_does_not_consume_offload_budget(tmp_path):
    """A long first-time sandbox setup must not shrink offload remaining."""
    import asyncio

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    now = loop.time()
    offload_remaining = 1.0
    offload_at = now + offload_remaining
    ctx = ToolCallContext(
        tool_call_id="tc-sandbox-slow",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=offload_at,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    class _SlowSandboxCM:
        async def __aenter__(self):
            await asyncio.sleep(0.35)
            sandbox = AsyncMock()
            sandbox.execute.return_value = ExecutionResult(0, "ok", "")
            return sandbox

        async def __aexit__(self, *args):
            return None

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
    )

    try:
        with patch(
            "qwenpaw.sandbox.create_sandbox",
            return_value=_SlowSandboxCM(),
        ):
            await _execute_in_sandbox(
                "echo ok",
                config,
                8.0,
                str(tmp_path),
                {"PATH": "/bin"},
            )
        # Without compensation remaining would be ~0.65; with it ~1.0.
        remaining = ctx.offload_deadline - loop.time()
        assert remaining == pytest.approx(offload_remaining, abs=0.08)
        assert remaining > 0.9
    finally:
        reset_call_context(token)


def test_cancel_stderr_message_distinguishes_timeout_and_user():
    import asyncio

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import CancelReason, ToolCallContext

    ctx = ToolCallContext(
        tool_call_id="tc-msg",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
        cancel_reason=CancelReason.TIMEOUT,
    )
    token = set_call_context(ctx)
    try:
        msg = _cancel_stderr_message(42.0)
        assert "TimeoutError" in msg
        assert "42.0" in msg

        ctx.cancel_reason = CancelReason.USER
        user_msg = _cancel_stderr_message(42.0)
        assert "cancelled by the user" in user_msg
        assert "Do not retry" in user_msg
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix non-sandbox subprocess path under test",
)
async def test_unix_shell_cancellederror_uses_timeout_stderr():
    """kill_deadline CancelledError must surface TimeoutError text on Unix."""
    import asyncio

    from qwenpaw.agents.tools.shell import execute_shell_command
    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import CancelReason, ToolCallContext

    ctx = ToolCallContext(
        tool_call_id="tc-unix-timeout",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
        cancel_reason=CancelReason.TIMEOUT,
    )
    token = set_call_context(ctx)

    proc = MagicMock()
    proc.returncode = -1
    proc.pid = 12345
    proc.wait = AsyncMock(return_value=-1)

    async def _fake_cleanup(proc_arg):
        return None

    cancelled_once = False

    async def _cancel_wait(awaitable, **_kwargs):
        nonlocal cancelled_once
        if not cancelled_once:
            cancelled_once = True
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            elif isinstance(awaitable, asyncio.Future):
                awaitable.cancel()
            raise asyncio.CancelledError()
        return await awaitable

    try:
        with (
            patch(
                "qwenpaw.agents.tools.shell.asyncio.create_subprocess_exec",
                AsyncMock(return_value=proc),
            ),
            patch(
                "qwenpaw.tool_calls.cancellable_wait",
                side_effect=_cancel_wait,
            ),
            patch(
                "qwenpaw.agents.tools.shell._cleanup_proc",
                side_effect=_fake_cleanup,
            ),
        ):
            result = await execute_shell_command(
                "sleep 99",
                timeout=7.5,
                sandbox_config=None,
            )
        text = result.content[0].text
        assert "TimeoutError" in text
        assert "7.5" in text
        assert "cancelled" not in text.lower()
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix non-sandbox subprocess path under test",
)
async def test_unix_shell_cancellederror_uses_user_cancel_stderr():
    import asyncio

    from qwenpaw.agents.tools.shell import execute_shell_command
    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import CancelReason, ToolCallContext

    ctx = ToolCallContext(
        tool_call_id="tc-unix-user",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
        cancel_reason=CancelReason.USER,
    )
    token = set_call_context(ctx)

    proc = MagicMock()
    proc.returncode = -1
    proc.pid = 12345
    proc.wait = AsyncMock(return_value=-1)

    async def _fake_cleanup(proc_arg):
        return None

    cancelled_once = False

    async def _cancel_wait(awaitable, **_kwargs):
        nonlocal cancelled_once
        if not cancelled_once:
            cancelled_once = True
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            elif isinstance(awaitable, asyncio.Future):
                awaitable.cancel()
            raise asyncio.CancelledError()
        return await awaitable

    try:
        with (
            patch(
                "qwenpaw.agents.tools.shell.asyncio.create_subprocess_exec",
                AsyncMock(return_value=proc),
            ),
            patch(
                "qwenpaw.tool_calls.cancellable_wait",
                side_effect=_cancel_wait,
            ),
            patch(
                "qwenpaw.agents.tools.shell._cleanup_proc",
                side_effect=_fake_cleanup,
            ),
        ):
            result = await execute_shell_command(
                "sleep 99",
                timeout=7.5,
                sandbox_config=None,
            )
        text = result.content[0].text
        assert "cancelled by the user" in text
        assert "Do not retry" in text
        assert "TimeoutError" not in text
    finally:
        reset_call_context(token)


def test_execute_subprocess_sync_honors_stop_event(tmp_path):
    """stop_event must kill the process tree before the full timeout."""
    import threading
    import time

    stop_event = threading.Event()

    def _arm_stop() -> None:
        time.sleep(0.15)
        stop_event.set()

    killed_pids: list[int] = []

    def _fake_kill(pid: int) -> None:
        killed_pids.append(pid)
        if sys.platform == "win32":
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    # Avoid /bin/sh on Windows (FileNotFound → except path returns -1
    # without calling the kill helper).
    if sys.platform == "win32":
        cmd = "ping -n 60 127.0.0.1 >NUL"
        shell_executable = None
    else:
        cmd = "sleep 30"
        shell_executable = "/bin/sh"

    armer = threading.Thread(target=_arm_stop)
    armer.start()
    started = time.monotonic()
    try:
        with patch(
            "qwenpaw.agents.tools.shell._kill_process_tree_win32",
            side_effect=_fake_kill,
        ):
            code, _stdout, _stderr = _execute_subprocess_sync(
                cmd,
                str(tmp_path),
                timeout=60.0,
                shell_executable=shell_executable,
                stop_event=stop_event,
            )
    finally:
        armer.join(timeout=2)

    elapsed = time.monotonic() - started
    assert code == -1
    assert killed_pids
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_windows_host_arms_kill_deadline():
    import asyncio

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-win-kill",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    def _fake_sync(*_args, **_kwargs):
        return 0, "ok", ""

    try:
        with patch(
            "qwenpaw.agents.tools.shell._execute_subprocess_sync",
            side_effect=_fake_sync,
        ):
            code, out, _err = await _execute_windows_host(
                "echo ok",
                "/tmp",
                3.5,
                {"PATH": "/bin"},
                None,
            )
        assert code == 0
        assert out == "ok"
        assert ctx.kill_deadline is not None
        remaining = ctx.kill_deadline - loop.time()
        assert remaining == pytest.approx(3.5, abs=0.5)
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_windows_host_cancel_bridges_stop_event():
    import asyncio
    import time

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import CancelReason, ToolCallContext

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-win-cancel",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    seen: dict[str, object] = {}

    def _fake_sync(
        _cmd,
        _cwd,
        _timeout,
        _env=None,
        _shell_executable=None,
        stop_event=None,
    ):
        seen["has_stop"] = stop_event is not None
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                seen["stopped"] = True
                return -1, "", ""
            time.sleep(0.02)
        return 0, "too-late", ""

    try:
        with patch(
            "qwenpaw.agents.tools.shell._execute_subprocess_sync",
            side_effect=_fake_sync,
        ):
            task = asyncio.create_task(
                _execute_windows_host(
                    "sleep 99",
                    "/tmp",
                    30.0,
                    {"PATH": "/bin"},
                    None,
                ),
            )
            await asyncio.sleep(0.05)
            assert ctx.kill_deadline is not None
            ctx.cancel_reason = CancelReason.USER
            ctx.cancel_event.set()
            code, _out, err = await asyncio.wait_for(task, timeout=2)
        # Thread may observe stop_event slightly after CancelledError returns.
        for _ in range(50):
            if seen.get("stopped"):
                break
            await asyncio.sleep(0.02)
        assert seen.get("has_stop") is True
        assert seen.get("stopped") is True
        assert code == -1
        assert "cancelled by the user" in err
        assert "Do not retry" in err
        assert "TimeoutError" not in err
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_windows_host_ctx_passes_no_sync_timeout():
    """Under ToolCallContext, sync must not get a frozen command timeout."""
    import asyncio
    import time

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-win-sync-to",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    seen: dict[str, object] = {}

    def _fake_sync(
        _cmd,
        _cwd,
        timeout,
        _env=None,
        _shell_executable=None,
        stop_event=None,
    ):
        seen["timeout"] = timeout
        start = time.monotonic()
        # Survive past the original command timeout (0.08s).
        while time.monotonic() - start < 0.2:
            if stop_event is not None and stop_event.is_set():
                return -1, "", f"sync-timeout-{timeout}"
            time.sleep(0.02)
        return 0, "survived", ""

    try:
        with patch(
            "qwenpaw.agents.tools.shell._execute_subprocess_sync",
            side_effect=_fake_sync,
        ):
            code, out, _err = await asyncio.wait_for(
                _execute_windows_host(
                    "sleep 99",
                    "/tmp",
                    0.08,
                    {"PATH": "/bin"},
                    None,
                ),
                timeout=2,
            )
        assert seen.get("timeout") is None
        assert code == 0
        assert out == "survived"
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_windows_host_extend_kill_and_no_deadline_ignore_sync_timeout():
    """extend_kill / no_deadline must not be overridden by sync timeout."""
    import asyncio
    import time

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import CancelReason, ToolCallContext

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-win-extend",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    seen: dict[str, object] = {}

    def _fake_sync(
        _cmd,
        _cwd,
        timeout,
        _env=None,
        _shell_executable=None,
        stop_event=None,
    ):
        seen["timeout"] = timeout
        start = time.monotonic()
        while time.monotonic() - start < 1.5:
            if stop_event is not None and stop_event.is_set():
                seen["stopped"] = True
                return -1, "", "stopped-by-event"
            if timeout is not None and time.monotonic() - start >= timeout:
                return -1, "", f"sync-timeout-{timeout}"
            time.sleep(0.02)
        return 0, "still-running", ""

    try:
        with patch(
            "qwenpaw.agents.tools.shell._execute_subprocess_sync",
            side_effect=_fake_sync,
        ):
            task = asyncio.create_task(
                _execute_windows_host(
                    "sleep 99",
                    "/tmp",
                    0.1,
                    {"PATH": "/bin"},
                    None,
                ),
            )
            await asyncio.sleep(0.05)
            assert ctx.kill_deadline is not None
            # Mimic extend_kill(+10s) then no_deadline clear.
            ctx.kill_deadline = loop.time() + 10.0
            ctx.deadline_changed_event.set()
            await asyncio.sleep(0.2)
            assert not task.done()
            ctx.kill_deadline = None
            ctx.deadline_changed_event.set()
            await asyncio.sleep(0.2)
            assert not task.done()
            # Cancel still terminates promptly via stop_event.
            ctx.cancel_reason = CancelReason.USER
            ctx.cancel_event.set()
            code, _out, err = await asyncio.wait_for(task, timeout=2)

        assert seen.get("timeout") is None
        assert "sync-timeout-" not in str(seen)
        assert seen.get("stopped") is True
        assert code == -1
        assert "cancelled by the user" in err
        assert "Do not retry" in err
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_windows_host_without_ctx_keeps_sync_timeout():
    """Direct/SDK calls (no ctx) still use the command timeout in sync."""
    seen: dict[str, object] = {}

    def _fake_sync(
        _cmd,
        _cwd,
        timeout,
        _env=None,
        _shell_executable=None,
        stop_event=None,
    ):
        seen["timeout"] = timeout
        return 0, "ok", ""

    with patch(
        "qwenpaw.agents.tools.shell._execute_subprocess_sync",
        side_effect=_fake_sync,
    ):
        code, out, _err = await _execute_windows_host(
            "echo ok",
            "/tmp",
            4.25,
            {"PATH": "/bin"},
            None,
        )
    assert code == 0
    assert out == "ok"
    assert seen.get("timeout") == 4.25


@pytest.mark.asyncio
async def test_windows_host_task_cancel_still_sets_stop_event():
    """force/task cancel without relying on bridge must still stop sync."""
    import asyncio
    import time

    from qwenpaw.tool_calls import reset_call_context, set_call_context
    from qwenpaw.tool_calls._context import ToolCallContext

    loop = asyncio.get_running_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-win-force-stop",
        tool_name="execute_shell_command",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=loop.time(),
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    seen: dict[str, object] = {}

    def _fake_sync(
        _cmd,
        _cwd,
        timeout,
        _env=None,
        _shell_executable=None,
        stop_event=None,
    ):
        seen["timeout"] = timeout
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                seen["stopped"] = True
                return -1, "", ""
            time.sleep(0.02)
        return 0, "leaked", ""

    try:
        with patch(
            "qwenpaw.agents.tools.shell._execute_subprocess_sync",
            side_effect=_fake_sync,
        ):
            task = asyncio.create_task(
                _execute_windows_host(
                    "sleep 99",
                    "/tmp",
                    30.0,
                    {"PATH": "/bin"},
                    None,
                ),
            )
            await asyncio.sleep(0.05)
            # Equivalence of force cancel: cancel the awaitable without
            # first setting cancel_event (bridge alone would not fire).
            assert not ctx.cancel_event.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        for _ in range(50):
            if seen.get("stopped"):
                break
            await asyncio.sleep(0.02)
        assert seen.get("timeout") is None
        assert seen.get("stopped") is True
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_execute_shell_command_win32_uses_windows_host():
    """Host shell on win32 must go through the dual-deadline helper."""
    from qwenpaw.agents.tools.shell import execute_shell_command

    with (
        patch("qwenpaw.agents.tools.shell.sys.platform", "win32"),
        patch(
            "qwenpaw.agents.tools.shell._execute_windows_host",
            AsyncMock(return_value=(0, "win-ok", "")),
        ) as mock_win,
        patch(
            "qwenpaw.agents.tools.shell.get_current_shell_command_timeout",
            return_value=None,
        ),
        patch(
            "qwenpaw.agents.tools.shell.get_current_workspace_dir",
            return_value=None,
        ),
        patch(
            "qwenpaw.agents.tools.shell.get_current_shell_command_executable",
            return_value=None,
        ),
    ):
        result = await execute_shell_command(
            "echo hi",
            timeout=9.0,
            sandbox_config=None,
        )

    mock_win.assert_awaited_once()
    assert "win-ok" in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix-only direct subprocess path",
)
async def test_non_dataclass_sandbox_config_ignored(
    monkeypatch,
    tmp_path,
):
    """Model-supplied non-SandboxConfig value must not crash replace().

    Regression test for GitHub issue #6731: when a model fills the
    ``sandbox_config`` parameter with a plain JSON value (e.g. ``{}``),
    ``dataclasses.replace()`` raises ``TypeError``. The fix discards
    any non-``SandboxConfig`` value and falls through to direct
    execution.
    """
    from qwenpaw.agents.tools.shell import execute_shell_command

    monkeypatch.setenv("SHELL", "/bin/sh")

    result = await execute_shell_command(
        "echo hello",
        cwd=tmp_path,
        sandbox_config={},
    )

    assert "hello" in result.content[0].text
