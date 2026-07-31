# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access,unused-variable
# pylint: disable=wrong-import-position
"""Unit tests for Windows Unelevated sandbox (WRITE_RESTRICTED, no admin).

Test structure:
    1. Factory routing (create_sandbox dispatches correctly)
    2. Shell command-line building
    3. Config fingerprint computation
    4. Random capability SID generation
    5. Environment block construction
    6. WindowsUnelevatedSandbox.execute() — success / violation / timeout
    7. WindowsUnelevatedSandbox stop/cleanup
"""

import asyncio
import ctypes
import sys
import types
from unittest.mock import MagicMock, patch

# -- Cross-platform stubs for ctypes.wintypes / ctypes.WinDLL ---------------
if sys.platform != "win32":
    if not hasattr(ctypes, "wintypes"):
        _wintypes = types.ModuleType("ctypes.wintypes")
        _wintypes.BYTE = ctypes.c_ubyte
        _wintypes.WORD = ctypes.c_ushort
        _wintypes.DWORD = ctypes.c_ulong
        _wintypes.LONG = ctypes.c_long
        _wintypes.ULONG = ctypes.c_ulong
        _wintypes.UINT = ctypes.c_uint
        _wintypes.INT = ctypes.c_int
        _wintypes.BOOL = ctypes.c_int
        _wintypes.BOOLEAN = ctypes.c_ubyte
        _wintypes.LARGE_INTEGER = ctypes.c_int64
        _wintypes.ULARGE_INTEGER = ctypes.c_uint64
        _wintypes.HANDLE = ctypes.c_void_p
        _wintypes.HLOCAL = ctypes.c_void_p
        _wintypes.HMODULE = ctypes.c_void_p
        _wintypes.HINSTANCE = ctypes.c_void_p
        _wintypes.HWND = ctypes.c_void_p
        _wintypes.WPARAM = ctypes.c_size_t
        _wintypes.LPARAM = ctypes.c_ssize_t
        _wintypes.LPCWSTR = ctypes.c_wchar_p
        _wintypes.LPWSTR = ctypes.c_wchar_p
        _wintypes.LPCSTR = ctypes.c_char_p
        _wintypes.LPSTR = ctypes.c_char_p
        ctypes.wintypes = _wintypes  # type: ignore[attr-defined]
        sys.modules["ctypes.wintypes"] = _wintypes
    if not hasattr(ctypes, "WinDLL"):

        class _WinDLLStub:
            def __init__(self, *a, **kw):
                raise OSError("ctypes.WinDLL unavailable on this platform")

        ctypes.WinDLL = _WinDLLStub  # type: ignore[attr-defined]
    if "msvcrt" not in sys.modules:
        _msvcrt = types.ModuleType("msvcrt")
        _msvcrt.LK_NBLCK = 0x2  # type: ignore[attr-defined]
        _msvcrt.LK_UNLCK = 0x0  # type: ignore[attr-defined]
        _msvcrt.locking = lambda *a, **kw: None  # type: ignore[attr-defined]
        sys.modules["msvcrt"] = _msvcrt
# -- End stubs ---------------------------------------------------------------

from qwenpaw.sandbox import MountSpec, SandboxConfig, SandboxMode
from qwenpaw.sandbox.windows_unelevated_sandbox import (
    _WC,
    WindowsUnelevatedSandbox,
    _build_shell_command_line,
    _compute_config_fingerprint,
    _make_env_block,
    _make_random_cap_sid_string,
)

# ============================================================================
# Factory routing (create_sandbox dispatches correctly)
# ============================================================================


class TestFactoryRouting:
    """Test that create_sandbox routes allow_read_all=True non-admin here."""

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._is_admin",
        return_value=False,
    )
    def test_allow_read_all_non_admin_routes_to_unelevated(
        self,
        mock_admin,
    ):
        """allow_read_all=True + non-admin → WindowsUnelevatedSandbox."""
        from qwenpaw.sandbox import create_sandbox

        config = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\Users\foo\project",
            allow_read_all=True,
        )
        sandbox = create_sandbox(config)
        assert isinstance(sandbox, WindowsUnelevatedSandbox)

    def test_allow_read_all_false_does_not_route_here(self):
        """allow_read_all=False routes to AppContainerSandbox."""
        from qwenpaw.sandbox import create_sandbox
        from qwenpaw.sandbox.windows_appcontainer_sandbox import (
            WindowsAppContainerSandbox,
        )

        config = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\Users\foo\project",
            allow_read_all=False,
        )
        sandbox = create_sandbox(config)
        assert isinstance(sandbox, WindowsAppContainerSandbox)
        assert not isinstance(sandbox, WindowsUnelevatedSandbox)


# ============================================================================
# Shell command-line building
# ============================================================================


class TestShellCommandLineBuilding:
    """Test _build_shell_command_line for various shell executables."""

    def test_default_cmd_exe(self):
        """No shell_executable → uses cmd.exe /c."""
        result = _build_shell_command_line("echo hello", None)
        assert result == 'cmd.exe /c "echo hello"'

    def test_explicit_cmd_exe(self):
        """Explicit cmd.exe path → uses /c flag."""
        result = _build_shell_command_line("dir", "cmd.exe")
        assert result == 'cmd.exe /c "dir"'

    def test_powershell_exe(self):
        """powershell.exe → uses PowerShell flags."""
        result = _build_shell_command_line("Get-Date", "powershell.exe")
        assert "-NoProfile" in result
        assert "-NonInteractive" in result
        assert "-ExecutionPolicy Bypass" in result
        assert '-Command "Get-Date"' in result

    def test_pwsh_exe(self):
        """pwsh.exe is recognized as PowerShell."""
        result = _build_shell_command_line("ls", "pwsh.exe")
        assert "-NoProfile" in result
        assert '-Command "ls"' in result

    def test_custom_shell(self):
        """Non-standard shell → uses -c flag (POSIX-style)."""
        result = _build_shell_command_line("ls -la", "/usr/bin/bash")
        assert result == '/usr/bin/bash -c "ls -la"'

    def test_quotes_escaped_in_powershell(self):
        """Quotes in command are escaped for PowerShell."""
        result = _build_shell_command_line(
            'Write-Output "hi"',
            "powershell.exe",
        )
        assert '\\"hi\\"' in result

    def test_powershell_names_recognized(self):
        """_WC.POWERSHELL_NAMES includes all PowerShell variants."""
        assert "powershell.exe" in _WC.POWERSHELL_NAMES
        assert "powershell" in _WC.POWERSHELL_NAMES
        assert "pwsh.exe" in _WC.POWERSHELL_NAMES
        assert "pwsh" in _WC.POWERSHELL_NAMES
        assert "cmd.exe" not in _WC.POWERSHELL_NAMES

    def test_cmd_names_recognized(self):
        """_WC.CMD_NAMES includes cmd variants."""
        assert "cmd.exe" in _WC.CMD_NAMES
        assert "cmd" in _WC.CMD_NAMES
        assert "powershell.exe" not in _WC.CMD_NAMES


# ============================================================================
# Config fingerprint computation
# ============================================================================


class TestConfigFingerprint:
    """Test _compute_config_fingerprint determinism and sensitivity."""

    def test_deterministic(self):
        """Same config → same fingerprint."""
        config = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            deny_paths=["~/.ssh"],
        )
        fp1 = _compute_config_fingerprint(config)
        fp2 = _compute_config_fingerprint(config)
        assert fp1 == fp2

    def test_different_workspace_differs(self):
        """Different workspace_dir → different fingerprint."""
        config1 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project1",
            allow_read_all=True,
        )
        config2 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project2",
            allow_read_all=True,
        )
        fp1 = _compute_config_fingerprint(config1)
        fp2 = _compute_config_fingerprint(config2)
        assert fp1 != fp2

    def test_different_mounts_differs(self):
        """Different mounts → different fingerprint."""
        config1 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            mounts=[MountSpec(path=r"C:\data", writable=True)],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            mounts=[MountSpec(path=r"C:\data", writable=False)],
        )
        fp1 = _compute_config_fingerprint(config1)
        fp2 = _compute_config_fingerprint(config2)
        assert fp1 != fp2

    def test_different_deny_paths_differs(self):
        """Different deny_paths → different fingerprint."""
        config1 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            deny_paths=["~/.ssh"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            deny_paths=["~/.gpg"],
        )
        fp1 = _compute_config_fingerprint(config1)
        fp2 = _compute_config_fingerprint(config2)
        assert fp1 != fp2

    def test_different_network_differs(self):
        """Different network_allow → different fingerprint."""
        config1 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            network_allow=["*"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            network_allow=[],
        )
        fp1 = _compute_config_fingerprint(config1)
        fp2 = _compute_config_fingerprint(config2)
        assert fp1 != fp2

    def test_fingerprint_is_hex_string(self):
        """Fingerprint is a valid hex string."""
        config = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        fp = _compute_config_fingerprint(config)
        # Truncated sha256 hex string (16 chars)
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)


# ============================================================================
# Random capability SID generation
# ============================================================================


class TestRandomCapSid:
    """Test _make_random_cap_sid_string format and uniqueness."""

    def test_format(self):
        """SID matches S-1-5-21-{a}-{b}-{c}-{d} pattern."""
        sid = _make_random_cap_sid_string()
        parts = sid.split("-")
        assert parts[0] == "S"
        assert parts[1] == "1"
        assert parts[2] == "5"
        assert parts[3] == "21"
        assert len(parts) == 8
        # Each sub-authority should be a valid integer
        for p in parts[4:]:
            int(p)

    def test_uniqueness(self):
        """Two calls produce different SIDs (with overwhelming probability)."""
        sid1 = _make_random_cap_sid_string()
        sid2 = _make_random_cap_sid_string()
        assert sid1 != sid2


# ============================================================================
# Environment block construction
# ============================================================================


class TestEnvBlock:
    """Test _make_env_block sorts entries and terminates correctly."""

    def _get_full_block(self, block):
        """Get the full environment block content."""
        return ctypes.wstring_at(ctypes.addressof(block), len(block))

    def test_sorted_output(self):
        """Environment block entries are sorted case-insensitively."""
        env = {"ZOO": "val3", "apple": "val1", "Banana": "val2"}
        block = _make_env_block(env)
        block_str = self._get_full_block(block)
        # Sorted case-insensitively: apple, Banana, ZOO
        assert block_str.index("apple=val1") < block_str.index(
            "Banana=val2",
        )
        assert block_str.index("Banana=val2") < block_str.index(
            "ZOO=val3",
        )

    def test_double_null_terminated(self):
        """Environment block ends with double null."""
        env = {"A": "1"}
        block = _make_env_block(env)
        block_str = self._get_full_block(block)
        assert "A=1" in block_str
        assert block_str.endswith("\x00\x00")

    def test_empty_env(self):
        """Empty env dict → just the double null terminator."""
        env = {}
        block = _make_env_block(env)
        assert block.value == ""


# ============================================================================
# WindowsUnelevatedSandbox.execute() — success / violation / timeout
# ============================================================================


class TestWindowsUnelevatedSandboxExecute:
    """Test execute() method with mocked process creation."""

    def _make_sandbox(self, **kwargs):
        defaults = {
            "mode": SandboxMode.WINDOWS,
            "workspace_dir": r"C:\project",
            "allow_read_all": True,
        }
        defaults.update(kwargs)
        config = SandboxConfig(**defaults)
        sandbox = WindowsUnelevatedSandbox(config)
        # Mark as initialized to skip real Win32 setup
        sandbox._initialized = True
        sandbox._h_token = MagicMock()
        sandbox._cap_psid = MagicMock()
        sandbox._cap_sid_string = "S-1-5-21-111-222-333-444"
        return sandbox

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._wait_and_read_process",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_success(self, mock_create, mock_wait):
        """Successful command returns exit_code=0, no violation."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        def fake_wait(*args, **kwargs):
            return (0, "hello world\n", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("echo hello world"))

        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert result.sandbox_violation is None
        assert result.timed_out is False

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._wait_and_read_process",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_violation_detected(self, mock_create, mock_wait):
        """Access denied in stderr → sandbox_violation is populated."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        def fake_wait(*args, **kwargs):
            return (1, "", "Access is denied\n", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("type C:\\secret.txt"))

        assert result.exit_code == 1
        assert result.sandbox_violation is not None
        assert "Access is denied" in result.sandbox_violation

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._wait_and_read_process",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_timeout(self, mock_create, mock_wait):
        """Process exceeds timeout → timed_out=True."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        def fake_wait(*args, **kwargs):
            return (1, "", "", True)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox(timeout_seconds=5)
        result = asyncio.run(
            sandbox.execute("ping -n 100 127.0.0.1"),
        )

        assert result.timed_out is True

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._get_kernel32",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_oserror(self, mock_create, mock_kernel32_fn):
        """CreateProcess failure → exit_code=-1, error in stderr."""
        mock_create.side_effect = OSError(
            "CreateProcessAsUserW failed: error=5",
        )
        mock_kernel32_fn.return_value = MagicMock()

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("whoami"))

        assert result.exit_code == -1
        assert "CreateProcessAsUserW failed" in result.stderr

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._wait_and_read_process",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_chinese_violation(self, mock_create, mock_wait):
        """Chinese locale violation patterns are detected."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        def fake_wait(*args, **kwargs):
            return (1, "", "\u62d2\u7edd\u8bbf\u95ee\u3002\n", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("dir C:\\secret"))

        assert result.sandbox_violation is not None

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._wait_and_read_process",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_network_proxy_env(self, mock_create, mock_wait):
        """No network_allow → proxy env vars are injected."""
        captured_env = {}

        def capture_create(h_token, cmd, cwd, env, *args, **kwargs):
            captured_env.update(env)
            return (
                1234,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

        mock_create.side_effect = capture_create

        def fake_wait(*args, **kwargs):
            return (0, "", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox(network_allow=[])
        asyncio.run(sandbox.execute("whoami"))

        assert captured_env["HTTP_PROXY"] == "http://127.0.0.1:9"
        assert captured_env["HTTPS_PROXY"] == "http://127.0.0.1:9"

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._wait_and_read_process",
    )
    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._create_process_as_user",
    )
    def test_execute_custom_cwd(self, mock_create, mock_wait):
        """Custom cwd is passed to process creation."""
        captured_cwd = []

        def capture_create(h_token, cmd, cwd, env, *args, **kwargs):
            captured_cwd.append(cwd)
            return (
                1234,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

        mock_create.side_effect = capture_create

        def fake_wait(*args, **kwargs):
            return (0, "", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        asyncio.run(sandbox.execute("dir", cwd=r"C:\other"))

        assert captured_cwd[0] == r"C:\other"


# ============================================================================
# WindowsUnelevatedSandbox stop/cleanup
# ============================================================================


class TestWindowsUnelevatedSandboxStop:
    """Test stop() releases token handles."""

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._get_kernel32",
    )
    def test_stop_closes_token(self, mock_kernel32_fn):
        """stop() closes the restricted token handle."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32

        config = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        sandbox = WindowsUnelevatedSandbox(config)
        sandbox._initialized = True
        sandbox._h_token = MagicMock()
        sandbox._cap_psid = MagicMock()
        sandbox._process_handle = None
        sandbox._job_handle = None

        asyncio.run(sandbox.stop())

        mock_kernel32.CloseHandle.assert_called()
        assert sandbox._h_token is None
        assert sandbox._initialized is False

    @patch(
        "qwenpaw.sandbox.windows_unelevated_sandbox._get_kernel32",
    )
    def test_stop_frees_cap_sid(self, mock_kernel32_fn):
        """stop() frees the capability SID pointer."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32

        config = SandboxConfig(
            mode=SandboxMode.WINDOWS,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        sandbox = WindowsUnelevatedSandbox(config)
        sandbox._initialized = True
        sandbox._h_token = MagicMock()
        sandbox._cap_psid = MagicMock()
        sandbox._process_handle = None
        sandbox._job_handle = None

        asyncio.run(sandbox.stop())

        mock_kernel32.LocalFree.assert_called()
        assert sandbox._cap_psid is None
