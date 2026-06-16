# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.tools.shell.

Covers:
- _collapse_newlines_outside_quotes
- _collapse_embedded_newlines
- _sanitize_win_cmd
- _read_temp_file
- _shell_basename
- _is_powershell / _is_cmd
- _extract_powershell_command
- smart_decode
- execute_shell_command (mocked subprocess)
"""
# pylint: disable=protected-access,unused-argument

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.agents.tools.shell import (
    _collapse_embedded_newlines,
    _collapse_newlines_outside_quotes,
    _extract_powershell_command,
    _is_cmd,
    _is_dangerous_self_kill,
    _is_powershell,
    _read_temp_file,
    _sanitize_win_cmd,
    _shell_basename,
    smart_decode,
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
# _collapse_newlines_outside_quotes
# ---------------------------------------------------------------------------


class TestCollapseNewlinesOutsideQuotes:
    """Tests for _collapse_newlines_outside_quotes."""

    def test_no_newlines(self):
        assert _collapse_newlines_outside_quotes("echo hello") == "echo hello"

    def test_unquoted_newline_to_space(self):
        assert _collapse_newlines_outside_quotes("echo\nhello") == "echo hello"

    def test_crlf_to_space(self):
        assert (
            _collapse_newlines_outside_quotes("echo\r\nhello") == "echo hello"
        )

    def test_single_quoted_newline_preserved(self):
        result = _collapse_newlines_outside_quotes("echo 'hello\nworld'")
        assert "\n" in result

    def test_double_quoted_newline_preserved(self):
        result = _collapse_newlines_outside_quotes('echo "hello\nworld"')
        assert "\n" in result

    def test_backslash_newline_continuation(self):
        result = _collapse_newlines_outside_quotes("echo \\\nhello")
        assert result == "echo hello"

    def test_backslash_before_normal_char_kept(self):
        result = _collapse_newlines_outside_quotes(r"echo \nhello")
        assert result == r"echo \nhello"

    def test_mixed_quoted_and_unquoted(self):
        cmd = 'echo "line1\nline2" && \necho second'
        result = _collapse_newlines_outside_quotes(cmd)
        # First \n inside double quotes preserved
        assert "line1\nline2" in result
        # Second \n outside quotes collapsed to space
        assert "echo second" in result


# ---------------------------------------------------------------------------
# _collapse_embedded_newlines
# ---------------------------------------------------------------------------


class TestCollapseEmbeddedNewlines:
    """Tests for _collapse_embedded_newlines."""

    def test_no_newlines_unchanged(self):
        assert _collapse_embedded_newlines("echo hello") == "echo hello"

    @patch("qwenpaw.agents.tools.shell.sys")
    def test_windows_collapses_all(self, mock_sys):
        mock_sys.platform = "win32"
        result = _collapse_embedded_newlines('echo "hello\nworld"')
        assert "\n" not in result

    @patch("qwenpaw.agents.tools.shell.sys")
    def test_unix_preserves_quoted(self, mock_sys):
        mock_sys.platform = "linux"
        result = _collapse_embedded_newlines('echo "hello\nworld"')
        assert "\n" in result


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
        import os

        assert _is_dangerous_self_kill(f"taskkill /F /PID {os.getpid()}")

    def test_taskkill_by_pid_parent(self):
        import os

        if hasattr(os, "getppid"):
            assert _is_dangerous_self_kill(f"taskkill /F /PID {os.getppid()}")

    def test_taskkill_by_pid_other_is_safe(self):
        assert not _is_dangerous_self_kill("taskkill /F /PID 99999")

    def test_kill_unix_pid_self(self):
        import os

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

        async def fake_wait_for(coro, timeout=None):
            return await coro

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"hello\n", b""),
        )
        mock_proc.returncode = 0
        mock_proc.pid = 12345

        with patch(
            "qwenpaw.agents.tools.shell.asyncio.create_subprocess_shell",
            AsyncMock(return_value=mock_proc),
        ), patch(
            "qwenpaw.agents.tools.shell.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            result = await execute_shell_command("echo hello")
            assert result.content is not None
            text = result.content[0]["text"]
            assert "hello" in text

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

        async def fake_wait_for(coro, timeout=None):
            return await coro

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"error msg\n"),
        )
        mock_proc.returncode = 1
        mock_proc.pid = 12345

        with patch(
            "qwenpaw.agents.tools.shell.asyncio.create_subprocess_shell",
            AsyncMock(return_value=mock_proc),
        ), patch(
            "qwenpaw.agents.tools.shell.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            result = await execute_shell_command("false")
            text = result.content[0]["text"]
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

        async def fake_wait_for(coro, timeout=None):
            return await coro

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0
        mock_proc.pid = 12345

        with patch(
            "qwenpaw.agents.tools.shell.asyncio.create_subprocess_shell",
            AsyncMock(return_value=mock_proc),
        ), patch(
            "qwenpaw.agents.tools.shell.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            from qwenpaw.agents.tools.shell import (
                execute_shell_command,
            )

            result = await execute_shell_command("")
            text = result.content[0]["text"]
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

        async def fake_wait_for(coro, timeout=None):
            return await coro

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0
        mock_proc.pid = 12345

        with patch(
            "qwenpaw.agents.tools.shell.asyncio.create_subprocess_shell",
            AsyncMock(return_value=mock_proc),
        ), patch(
            "qwenpaw.agents.tools.shell.asyncio.wait_for",
            side_effect=fake_wait_for,
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

        async def fake_wait_for(coro, timeout=None):
            return await coro

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0
        mock_proc.pid = 12345

        with patch(
            "qwenpaw.agents.tools.shell.asyncio.create_subprocess_shell",
            AsyncMock(return_value=mock_proc),
        ), patch(
            "qwenpaw.agents.tools.shell.asyncio.wait_for",
            side_effect=fake_wait_for,
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
