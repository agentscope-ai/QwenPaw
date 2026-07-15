# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access,unused-variable
"""Unit tests for Windows Restricted-Token sandbox (WRITE_RESTRICTED backend).

Test structure mirrors test_windows_sandbox.py:
    1. Factory routing (create_sandbox dispatches correctly)
    2. Shell command-line building
    3. Config fingerprint computation
    4. Random capability SID generation
    5. Environment block construction
    6. User provisioning helpers
    7. WFP network filtering
    8. ACL application logic
    9. Sandbox metadata and instance management
    10. WindowsRestrictedSandbox.execute() — success / violation / timeout
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from qwenpaw.sandbox import MountSpec, SandboxConfig, SandboxMode
from qwenpaw.sandbox.windows_restricted_sandbox import (
    WindowsRestrictedSandbox,
    _AclEntry,
    _build_shell_command_line,
    _compute_config_fingerprint,
    _make_env_block,
    _make_random_cap_sid_string,
    _random_password,
    _sandboxes_dir,
)
from qwenpaw.sandbox.windows_sandbox import (
    _is_cmd_exe,
    _is_powershell_exe,
)

# ============================================================================
# Factory routing (create_sandbox dispatches correctly)
# ============================================================================


class TestFactoryRouting:
    """Test that create_sandbox routes allow_read_all=True to this backend."""

    def test_allow_read_all_true_routes_to_restricted(self):
        """allow_read_all=True → WindowsRestrictedSandbox."""
        from qwenpaw.sandbox import create_sandbox

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            allow_read_all=True,
        )
        sandbox = create_sandbox(config)
        assert isinstance(sandbox, WindowsRestrictedSandbox)

    def test_allow_read_all_false_does_not_route_here(self):
        """allow_read_all=False → WindowsSandbox (not this backend)."""
        from qwenpaw.sandbox import create_sandbox
        from qwenpaw.sandbox.windows_sandbox import WindowsSandbox

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            allow_read_all=False,
        )
        sandbox = create_sandbox(config)
        assert isinstance(sandbox, WindowsSandbox)
        assert not isinstance(sandbox, WindowsRestrictedSandbox)


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

    def test_is_powershell_exe(self):
        """_is_powershell_exe recognizes all PowerShell variants."""
        assert _is_powershell_exe("powershell.exe") is True
        assert _is_powershell_exe("powershell") is True
        assert _is_powershell_exe("pwsh.exe") is True
        assert _is_powershell_exe("pwsh") is True
        # Full path with OS-appropriate separator
        full = os.path.join("C:", "Windows", "powershell.exe")
        assert _is_powershell_exe(full) is True
        assert _is_powershell_exe("cmd.exe") is False
        assert _is_powershell_exe(None) is False

    def test_is_cmd_exe(self):
        """_is_cmd_exe recognizes cmd variants."""
        assert _is_cmd_exe("cmd.exe") is True
        assert _is_cmd_exe("cmd") is True
        # Full path with OS-appropriate separator
        full = os.path.join("C:", "Windows", "System32", "cmd.exe")
        assert _is_cmd_exe(full) is True
        assert _is_cmd_exe("powershell.exe") is False
        assert _is_cmd_exe(None) is False


# ============================================================================
# Config fingerprint computation
# ============================================================================


class TestConfigFingerprint:
    """Test _compute_config_fingerprint determinism and sensitivity."""

    def test_deterministic(self):
        """Same config → same fingerprint."""
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
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
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project1",
            allow_read_all=True,
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project2",
            allow_read_all=True,
        )
        fp1 = _compute_config_fingerprint(config1)
        fp2 = _compute_config_fingerprint(config2)
        assert fp1 != fp2

    def test_different_mounts_differs(self):
        """Different mounts → different fingerprint."""
        config1 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            mounts=[MountSpec(path=r"C:\data", writable=True)],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
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
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            deny_paths=["~/.ssh"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
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
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            network_allow=["*"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
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
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        fp = _compute_config_fingerprint(config)
        # Truncated sha256 hex string (16 chars, matching AppContainer backend)
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
        """Get the full environment block content including embedded nulls."""
        import ctypes as ct

        return ct.wstring_at(ct.addressof(block), len(block))

    def test_sorted_output(self):
        """Environment block entries are sorted case-insensitively."""
        env = {"ZOO": "val3", "apple": "val1", "Banana": "val2"}
        block = _make_env_block(env)
        block_str = self._get_full_block(block)
        # Sorted case-insensitively: apple, Banana, ZOO
        assert block_str.index("apple=val1") < block_str.index("Banana=val2")
        assert block_str.index("Banana=val2") < block_str.index("ZOO=val3")

    def test_double_null_terminated(self):
        """Environment block ends with double null."""
        env = {"A": "1"}
        block = _make_env_block(env)
        block_str = self._get_full_block(block)
        # Should contain "A=1" followed by double null
        assert "A=1" in block_str
        assert block_str.endswith("\x00\x00")

    def test_empty_env(self):
        """Empty env dict → just the double null terminator."""
        env = {}
        block = _make_env_block(env)
        # First character accessible via .value is empty (first null)
        assert block.value == ""


# ============================================================================
# User provisioning helpers
# ============================================================================


class TestUserProvisioning:
    """Test user account provisioning logic with mocked Win32 APIs."""

    def test_random_password_length(self):
        """_random_password generates passwords of the requested length."""
        pw = _random_password(32)
        assert len(pw) == 32

    def test_random_password_default(self):
        """Default password is 24 characters."""
        pw = _random_password()
        assert len(pw) == 24

    def test_random_password_uniqueness(self):
        """Two calls produce different passwords."""
        pw1 = _random_password()
        pw2 = _random_password()
        assert pw1 != pw2

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_netapi32")
    def test_ensure_local_user_creates_new(self, mock_netapi32_fn):
        """NetUserAdd succeeds → returns True."""
        mock_netapi32 = MagicMock()
        mock_netapi32.NetUserAdd.return_value = 0  # NERR_Success
        mock_netapi32_fn.return_value = mock_netapi32

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _ensure_local_user,
        )

        result = _ensure_local_user("qwenpaw_test", "P@ssw0rd!")
        assert result is True
        mock_netapi32.NetUserAdd.assert_called_once()

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_netapi32")
    def test_ensure_local_user_updates_existing(self, mock_netapi32_fn):
        """Existing user → updates password via NetUserSetInfo."""
        mock_netapi32 = MagicMock()
        mock_netapi32.NetUserAdd.return_value = 2224  # NERR_UserExists
        mock_netapi32.NetUserSetInfo.return_value = 0  # NERR_Success
        mock_netapi32_fn.return_value = mock_netapi32

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _ensure_local_user,
        )

        result = _ensure_local_user("qwenpaw_existing", "NewP@ss!")
        assert result is True
        mock_netapi32.NetUserSetInfo.assert_called_once()

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_netapi32")
    def test_ensure_local_user_both_fail(self, mock_netapi32_fn):
        """Both create and update fail → returns False."""
        mock_netapi32 = MagicMock()
        mock_netapi32.NetUserAdd.return_value = 2224
        mock_netapi32.NetUserSetInfo.return_value = 5  # Access denied
        mock_netapi32_fn.return_value = mock_netapi32

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _ensure_local_user,
        )

        result = _ensure_local_user("qwenpaw_fail", "P@ss!")
        assert result is False

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_netapi32")
    def test_ensure_local_group_success(self, mock_netapi32_fn):
        """NetLocalGroupAdd succeeds → returns True."""
        mock_netapi32 = MagicMock()
        mock_netapi32.NetLocalGroupAdd.return_value = 0
        mock_netapi32_fn.return_value = mock_netapi32

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _ensure_local_group,
        )

        result = _ensure_local_group("QwenpawUsers", "Test group")
        assert result is True

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_netapi32")
    def test_ensure_local_group_already_exists(self, mock_netapi32_fn):
        """NetLocalGroupAdd returns ERROR_ALIAS_EXISTS → still True."""
        mock_netapi32 = MagicMock()
        # ERROR_ALIAS_EXISTS
        mock_netapi32.NetLocalGroupAdd.return_value = 1379
        mock_netapi32_fn.return_value = mock_netapi32

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _ensure_local_group,
        )

        result = _ensure_local_group("QwenpawUsers", "Test group")
        assert result is True

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_netapi32")
    def test_ensure_local_group_failure(self, mock_netapi32_fn):
        """NetLocalGroupAdd returns unexpected error → False."""
        mock_netapi32 = MagicMock()
        mock_netapi32.NetLocalGroupAdd.return_value = 5  # ACCESS_DENIED
        mock_netapi32_fn.return_value = mock_netapi32

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _ensure_local_group,
        )

        result = _ensure_local_group("QwenpawUsers", "Test group")
        assert result is False


# ============================================================================
# WFP network filtering
# ============================================================================


class TestWFPNetworkFiltering:
    """Test firewall rule installation logic."""

    @patch("subprocess.run")
    def test_install_wfp_block_success(self, mock_run):
        """PowerShell rule creation succeeds → returns True."""
        mock_run.return_value = MagicMock(returncode=0)

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _install_wfp_block_filters,
        )

        result = _install_wfp_block_filters(
            "qwenpaw_abc",
            "S-1-5-21-111-222-333-444",
        )
        assert result is True
        mock_run.assert_called_once()

        # Verify PowerShell was called
        call_args = mock_run.call_args[0][0]
        assert "powershell.exe" in call_args

    @patch("subprocess.run")
    def test_install_wfp_block_failure(self, mock_run):
        """PowerShell returns non-zero → returns False."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"Access denied",
        )

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _install_wfp_block_filters,
        )

        result = _install_wfp_block_filters(
            "qwenpaw_abc",
            "S-1-5-21-111-222-333-444",
        )
        assert result is False

    @patch("subprocess.run")
    def test_install_wfp_rule_names(self, mock_run):
        """Firewall rules are named QwenPaw_Block_{username}_{In|Out}."""
        mock_run.return_value = MagicMock(returncode=0)

        from qwenpaw.sandbox.windows_restricted_sandbox import (
            _install_wfp_block_filters,
        )

        _install_wfp_block_filters("qwenpaw_xyz", "S-1-5-21-111-222-333-444")

        call_args = mock_run.call_args[0][0]
        ps_command = call_args[-1]  # Last argument is the PowerShell command
        assert "QwenPaw_Block_qwenpaw_xyz_Out" in ps_command
        assert "QwenPaw_Block_qwenpaw_xyz_In" in ps_command


# ============================================================================
# ACL application logic
# ============================================================================


class TestACLApplication:
    """Test _apply_all_acls logic with mocked Win32 ACL APIs."""

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._allow_null_device")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_deny_all_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_read_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_ace")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._ensure_python_dir_group_acl",
    )
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox._get_python_install_dir",
    )
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._string_to_sid")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=True)
    def test_workspace_gets_full_access(
        self,
        mock_isdir,
        mock_exists,
        mock_kernel32_fn,
        mock_str_to_sid,
        mock_python_dir,
        mock_python_acl,
        mock_allow_ace,
        mock_read_ace,
        mock_deny_ace,
        mock_null_device,
    ):
        """Workspace gets full access ACEs for both cap and user SIDs."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32
        mock_str_to_sid.return_value = MagicMock()
        mock_python_dir.return_value = None
        mock_allow_ace.return_value = True
        mock_read_ace.return_value = True

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )

        from qwenpaw.sandbox.windows_restricted_sandbox import _apply_all_acls

        entries = _apply_all_acls(config, "S-1-5-21-cap", "S-1-5-21-user")

        # Workspace should have allow_full for both cap and user
        ws_entries = [e for e in entries if e.path == r"C:\project"]
        assert any(
            e.access_mode == "allow_full" and e.sid_type == "cap"
            for e in ws_entries
        )
        assert any(
            e.access_mode == "allow_full" and e.sid_type == "user"
            for e in ws_entries
        )

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._allow_null_device")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_deny_all_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_read_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_ace")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._ensure_python_dir_group_acl",
    )
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox._get_python_install_dir",
    )
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._string_to_sid")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=True)
    def test_readonly_mount_gets_read_ace(
        self,
        mock_isdir,
        mock_exists,
        mock_kernel32_fn,
        mock_str_to_sid,
        mock_python_dir,
        mock_python_acl,
        mock_allow_ace,
        mock_read_ace,
        mock_deny_ace,
        mock_null_device,
    ):
        """Read-only mount gets allow_read for both cap and user SIDs."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32
        mock_str_to_sid.return_value = MagicMock()
        mock_python_dir.return_value = None
        mock_allow_ace.return_value = True
        mock_read_ace.return_value = True

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            mounts=[MountSpec(path=r"C:\readonly", writable=False)],
        )

        from qwenpaw.sandbox.windows_restricted_sandbox import _apply_all_acls

        entries = _apply_all_acls(config, "S-1-5-21-cap", "S-1-5-21-user")

        mount_entries = [e for e in entries if e.path == r"C:\readonly"]
        assert any(
            e.access_mode == "allow_read" and e.sid_type == "cap"
            for e in mount_entries
        )
        assert any(
            e.access_mode == "allow_read" and e.sid_type == "user"
            for e in mount_entries
        )

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._allow_null_device")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_deny_all_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_read_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_ace")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._ensure_python_dir_group_acl",
    )
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox._get_python_install_dir",
    )
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._string_to_sid")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=True)
    def test_deny_path_gets_deny_ace(
        self,
        mock_isdir,
        mock_exists,
        mock_kernel32_fn,
        mock_str_to_sid,
        mock_python_dir,
        mock_python_acl,
        mock_allow_ace,
        mock_read_ace,
        mock_deny_ace,
        mock_null_device,
    ):
        """Deny paths get deny_all ACE for user SID."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32
        mock_str_to_sid.return_value = MagicMock()
        mock_python_dir.return_value = None
        mock_allow_ace.return_value = True
        mock_read_ace.return_value = True
        mock_deny_ace.return_value = True

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            deny_paths=[r"C:\Users\testuser\.ssh"],
        )

        from qwenpaw.sandbox.windows_restricted_sandbox import _apply_all_acls

        entries = _apply_all_acls(config, "S-1-5-21-cap", "S-1-5-21-user")

        deny_entries = [e for e in entries if e.access_mode == "deny_all"]
        assert len(deny_entries) == 1
        assert deny_entries[0].sid_type == "user"
        assert r".ssh" in deny_entries[0].path

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._allow_null_device")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_deny_all_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_read_ace")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._add_allow_ace")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._ensure_python_dir_group_acl",
    )
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox._get_python_install_dir",
    )
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._string_to_sid")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=True)
    def test_writable_mount_gets_full_access(
        self,
        mock_isdir,
        mock_exists,
        mock_kernel32_fn,
        mock_str_to_sid,
        mock_python_dir,
        mock_python_acl,
        mock_allow_ace,
        mock_read_ace,
        mock_deny_ace,
        mock_null_device,
    ):
        """Writable mount gets full access for both cap and user SIDs."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32
        mock_str_to_sid.return_value = MagicMock()
        mock_python_dir.return_value = None
        mock_allow_ace.return_value = True
        mock_read_ace.return_value = True

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
            mounts=[MountSpec(path=r"C:\shared", writable=True)],
        )

        from qwenpaw.sandbox.windows_restricted_sandbox import _apply_all_acls

        entries = _apply_all_acls(config, "S-1-5-21-cap", "S-1-5-21-user")

        mount_entries = [e for e in entries if e.path == r"C:\shared"]
        assert any(
            e.access_mode == "allow_full" and e.sid_type == "cap"
            for e in mount_entries
        )
        assert any(
            e.access_mode == "allow_full" and e.sid_type == "user"
            for e in mount_entries
        )


# ============================================================================
# Sandbox metadata and instance management
# ============================================================================


class TestSandboxMetadata:
    """Test sandbox metadata directory and persistence logic."""

    def test_sandboxes_dir(self):
        """_sandboxes_dir returns state_dir / 'sandboxes'."""
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".qwenpaw"
            result = _sandboxes_dir(state_dir)
            assert result == state_dir / "sandboxes"
            assert result.name == "sandboxes"

    def test_acl_entry_dataclass(self):
        """_AclEntry stores path, access_mode, and sid_type."""
        entry = _AclEntry(
            path=r"C:\project",
            access_mode="allow_full",
            sid_type="cap",
        )
        assert entry.path == r"C:\project"
        assert entry.access_mode == "allow_full"
        assert entry.sid_type == "cap"


# ============================================================================
# WindowsRestrictedSandbox.execute() — success / violation / timeout
# ============================================================================


class TestWindowsRestrictedSandboxExecute:
    """Test execute() method with mocked process creation."""

    def _make_sandbox(self, **kwargs):
        defaults = {
            "mode": SandboxMode.APPCONTAINER,
            "workspace_dir": r"C:\project",
            "allow_read_all": True,
        }
        defaults.update(kwargs)
        config = SandboxConfig(**defaults)
        sandbox = WindowsRestrictedSandbox(config)
        return sandbox

    def _make_mock_instance(self):
        """Creates a mock _SandboxInstance for testing."""
        instance = MagicMock()
        instance.h_token = MagicMock()
        instance.username = "qwenpaw_test"
        instance.profile_dir = r"C:\Users\qwenpaw_test"
        instance.sandbox_id = "qwenpaw_test"
        instance.config_fingerprint = "abc123"
        return instance

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
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

        async def fake_wait(*args, **kwargs):
            return (0, "hello world\n", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        result = asyncio.run(sandbox.execute("echo hello world"))

        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert result.sandbox_violation is None
        assert result.timed_out is False

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
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

        async def fake_wait(*args, **kwargs):
            return (1, "", "Access is denied\n", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        result = asyncio.run(sandbox.execute("type C:\\secret.txt"))

        assert result.exit_code == 1
        assert result.sandbox_violation is not None
        assert "Access is denied" in result.sandbox_violation

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
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

        async def fake_wait(*args, **kwargs):
            return (1, "", "", True)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox(timeout_seconds=5)
        sandbox._instance = self._make_mock_instance()
        result = asyncio.run(sandbox.execute("ping -n 100 127.0.0.1"))

        assert result.timed_out is True

    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
    )
    def test_execute_oserror(self, mock_create):
        """CreateProcess failure → exit_code=-1, error in stderr."""
        mock_create.side_effect = OSError(
            "CreateProcess failed: error=5 "
            "(CreateProcessWithTokenW also failed: 1314)",
        )

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        result = asyncio.run(sandbox.execute("whoami"))

        assert result.exit_code == -1
        assert "CreateProcess failed" in result.stderr

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
    )
    def test_execute_violation_stdout_fail(self, mock_create, mock_wait):
        """Violation pattern in stdout (with non-zero exit) is detected."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        async def fake_wait(*args, **kwargs):
            return (1, "System error 5 has occurred\n", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        result = asyncio.run(sandbox.execute("del C:\\protected\\file.txt"))

        assert result.sandbox_violation is not None
        assert "error 5" in result.sandbox_violation

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
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

        async def fake_wait(*args, **kwargs):
            return (1, "", "\u62d2\u7edd\u8bbf\u95ee\u3002\n", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        result = asyncio.run(sandbox.execute("dir C:\\secret"))

        assert result.sandbox_violation is not None

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
    )
    def test_execute_env_overrides(self, mock_create, mock_wait):
        """Execute passes correct environment with sandbox user identity."""
        captured_env = {}

        def capture_create(h_token, cmd, cwd, env, **kwargs):
            captured_env.update(env)
            return (1234, MagicMock(), MagicMock(), MagicMock(), MagicMock())

        mock_create.side_effect = capture_create

        async def fake_wait(*args, **kwargs):
            return (0, "", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        asyncio.run(sandbox.execute("whoami"))

        assert captured_env["USERNAME"] == "qwenpaw_test"
        assert r"qwenpaw_test" in captured_env["USERPROFILE"]

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._wait_and_read_process")
    @patch(
        "qwenpaw.sandbox.windows_restricted_sandbox"
        "._create_process_with_token",
    )
    def test_execute_custom_cwd(self, mock_create, mock_wait):
        """Custom cwd is passed to process creation."""
        captured_cwd = []

        def capture_create(h_token, cmd, cwd, env, **kwargs):
            captured_cwd.append(cwd)
            return (1234, MagicMock(), MagicMock(), MagicMock(), MagicMock())

        mock_create.side_effect = capture_create

        async def fake_wait(*args, **kwargs):
            return (0, "", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        sandbox._instance = self._make_mock_instance()
        asyncio.run(sandbox.execute("dir", cwd=r"C:\other"))

        assert captured_cwd[0] == r"C:\other"


# ============================================================================
# WindowsRestrictedSandbox stop/cleanup
# ============================================================================


class TestWindowsRestrictedSandboxStop:
    """Test stop() and async context manager cleanup."""

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._release_sandbox")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    def test_stop_terminates_job(self, mock_kernel32_fn, mock_release):
        """stop() calls TerminateJobObject when job_handle is present."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32

        async def fake_release(inst):
            pass

        mock_release.side_effect = fake_release

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        sandbox = WindowsRestrictedSandbox(config)
        sandbox._instance = MagicMock()
        sandbox._job_handle = MagicMock()
        sandbox._process_id = 1234

        asyncio.run(sandbox.stop())

        mock_kernel32.TerminateJobObject.assert_called_once()
        assert sandbox._job_handle is None
        assert sandbox._process_id is None

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._release_sandbox")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    def test_stop_without_job_terminates_process(
        self,
        mock_kernel32_fn,
        mock_release,
    ):
        """stop() uses OpenProcess+TerminateProcess when no job handle."""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenProcess.return_value = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32

        async def fake_release(inst):
            pass

        mock_release.side_effect = fake_release

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        sandbox = WindowsRestrictedSandbox(config)
        sandbox._instance = MagicMock()
        sandbox._job_handle = None
        sandbox._process_id = 5678

        asyncio.run(sandbox.stop())

        mock_kernel32.OpenProcess.assert_called_once()
        mock_kernel32.TerminateProcess.assert_called_once()

    @patch("qwenpaw.sandbox.windows_restricted_sandbox._release_sandbox")
    @patch("qwenpaw.sandbox.windows_restricted_sandbox._get_kernel32")
    def test_stop_releases_instance(self, mock_kernel32_fn, mock_release):
        """stop() releases the sandbox instance reference."""
        mock_kernel32 = MagicMock()
        mock_kernel32_fn.return_value = mock_kernel32

        released = []

        async def fake_release(inst):
            released.append(inst)

        mock_release.side_effect = fake_release

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=True,
        )
        sandbox = WindowsRestrictedSandbox(config)
        mock_instance = MagicMock()
        sandbox._instance = mock_instance
        sandbox._job_handle = None
        sandbox._process_id = None

        asyncio.run(sandbox.stop())

        assert released == [mock_instance]
        assert sandbox._instance is None
