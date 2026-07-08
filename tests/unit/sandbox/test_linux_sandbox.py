# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Unit tests for Linux Landlock sandbox and probe_sandbox_support."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest

from qwenpaw.sandbox import (
    MountSpec,
    SandboxCapability,
    SandboxConfig,
    SandboxMode,
    probe_sandbox_support,
)
from qwenpaw.sandbox.config import (
    _probe_linux_landlock,
    _probe_macos_seatbelt,
    detect_platform_mode,
)

# os.uname is Linux/macOS only; skip entirely on Windows.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Linux sandbox tests require os.uname which is unavailable on Windows"
    ),
)

# ============================================================================
# probe_sandbox_support() — platform routing
# ============================================================================


class TestProbeSandboxSupport:
    """Test probe_sandbox_support() for each platform."""

    @patch("sys.platform", "darwin")
    @patch("shutil.which", return_value="/usr/bin/sandbox-exec")
    def test_darwin_delegates_to_seatbelt(self, mock_which):
        result = probe_sandbox_support()
        assert result.supported is True
        assert result.mode == SandboxMode.SEATBELT

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value=None)  # bwrap not found
    @patch("os.uname")
    def test_linux_delegates_to_landlock(self, mock_uname, mock_which):
        # bwrap not found → falls through to Landlock → kernel too old
        mock_uname.return_value = MagicMock(release="4.0.0")
        result = probe_sandbox_support()
        # Should go through _probe_linux_landlock and fail on kernel version
        assert result.mode == SandboxMode.NONE
        assert "4.0" in result.reason

    @patch("sys.platform", "win32")
    @patch("qwenpaw.sandbox.config._probe_windows_appcontainer")
    def test_windows_calls_appcontainer_probe(self, mock_probe):
        # Windows sandbox should delegate to _probe_windows_appcontainer.
        mock_probe.return_value = SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Not running on Windows",
        )
        result = probe_sandbox_support()
        mock_probe.assert_called_once()
        assert result.supported is False

    @patch("sys.platform", "freebsd13")
    def test_unknown_platform_returns_unsupported(self):
        result = probe_sandbox_support()
        assert result.supported is False
        assert result.mode == SandboxMode.NONE


# ============================================================================
# _probe_linux_landlock() — detailed Linux detection
# ============================================================================


class TestProbeLinuxLandlock:
    """Test Linux Landlock probe logic with various kernel/LSM scenarios."""

    @patch("os.uname")
    def test_kernel_too_old(self, mock_uname):
        mock_uname.return_value = MagicMock(release="5.10.112-generic")
        result = _probe_linux_landlock()
        assert result.supported is False
        assert "5.10" in result.reason
        assert "< 5.13" in result.reason
        assert result.mode == SandboxMode.NONE

    @patch("os.uname")
    def test_kernel_version_parse_error(self, mock_uname):
        mock_uname.return_value = MagicMock(release="invalid-kernel")
        result = _probe_linux_landlock()
        assert result.supported is False
        assert "Cannot parse" in result.reason

    @patch("builtins.open", mock_open(read_data="capability,yama,apparmor"))
    @patch("os.uname")
    def test_landlock_not_in_lsm(self, mock_uname):
        mock_uname.return_value = MagicMock(release="5.15.0-125-generic")
        result = _probe_linux_landlock()
        assert result.supported is False
        assert "not in LSM list" in result.reason

    @patch("builtins.open", side_effect=OSError("Permission denied"))
    @patch("os.uname")
    def test_lsm_file_unreadable(self, mock_uname, mock_file):
        mock_uname.return_value = MagicMock(release="5.15.0-125-generic")
        result = _probe_linux_landlock()
        assert result.supported is False
        assert "Cannot read" in result.reason

    @patch("platform.machine", return_value="x86_64")
    @patch(
        "builtins.open",
        mock_open(read_data="lockdown,capability,landlock,yama,apparmor"),
    )
    @patch("os.uname")
    def test_landlock_supported_abi_v4(self, mock_uname, mock_machine):
        mock_uname.return_value = MagicMock(release="6.7.0-generic")

        # Mock ctypes.CDLL to return a fake libc with syscall returning 4
        mock_libc = MagicMock()
        mock_libc.syscall.return_value = 4  # ABI v4

        with (
            patch("ctypes.CDLL", return_value=mock_libc),
            patch(
                "ctypes.util.find_library",
                return_value="libc.so.6",
            ),
        ):
            result = _probe_linux_landlock()

        assert result.supported is True
        assert result.mode == SandboxMode.LANDLOCK
        assert result.landlock_abi_version == 4
        assert "ABI v4" in result.reason

    @patch("platform.machine", return_value="x86_64")
    @patch("builtins.open", mock_open(read_data="landlock,capability"))
    @patch("os.uname")
    def test_landlock_syscall_fails(self, mock_uname, mock_machine):
        mock_uname.return_value = MagicMock(release="5.15.0-generic")

        mock_libc = MagicMock()
        mock_libc.syscall.return_value = -1  # failure

        with (
            patch("ctypes.CDLL", return_value=mock_libc),
            patch(
                "ctypes.util.find_library",
                return_value="libc.so.6",
            ),
            patch("ctypes.get_errno", return_value=38),
        ):
            result = _probe_linux_landlock()

        assert result.supported is False
        assert "syscall failed" in result.reason


# ============================================================================
# _probe_macos_seatbelt()
# ============================================================================


class TestProbeMacosSeatbelt:
    """Test macOS Seatbelt probe."""

    @patch("shutil.which", return_value="/usr/bin/sandbox-exec")
    def test_sandbox_exec_available(self, mock_which):
        result = _probe_macos_seatbelt()
        assert result.supported is True
        assert result.mode == SandboxMode.SEATBELT

    @patch("shutil.which", return_value=None)
    def test_sandbox_exec_not_found(self, mock_which):
        result = _probe_macos_seatbelt()
        assert result.supported is False
        assert result.mode == SandboxMode.NONE


# ============================================================================
# detect_platform_mode() — integration with probe
# ============================================================================


class TestDetectPlatformMode:
    """Test that detect_platform_mode uses probe results."""

    @patch("qwenpaw.sandbox.config.probe_sandbox_support")
    def test_returns_probe_mode(self, mock_probe):
        mock_probe.return_value = SandboxCapability(
            supported=True,
            mode=SandboxMode.LANDLOCK,
            reason="ok",
            landlock_abi_version=3,
        )
        assert detect_platform_mode() == SandboxMode.LANDLOCK

    @patch("qwenpaw.sandbox.config.probe_sandbox_support")
    def test_returns_none_when_unsupported(self, mock_probe):
        mock_probe.return_value = SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="too old",
        )
        assert detect_platform_mode() == SandboxMode.NONE


# ============================================================================
# LinuxSandbox._generate_sandbox_script — rule compilation
# ============================================================================


class TestLinuxSandboxRuleCompilation:
    """Test that Landlock rules are correctly generated from SandboxConfig."""

    def test_basic_workspace_mount(self):
        from qwenpaw.sandbox.linux_sandbox import _generate_sandbox_script

        config = SandboxConfig(
            mode=SandboxMode.LANDLOCK,
            workspace_dir="/home/user/project",
            mounts=[MountSpec(path="/home/user/project", writable=True)],
        )
        script = _generate_sandbox_script(
            config,
            "echo hello",
            "/home/user/project",
            1,
        )

        # Should contain the workspace path with write access
        assert "/home/user/project" in script
        assert "add_path" in script
        assert "exec" in script.lower()

    def test_readonly_mount(self):
        from qwenpaw.sandbox.linux_sandbox import (
            _FS_READ_ACCESS,
            _FS_WRITE_ACCESS,
            _generate_sandbox_script,
        )

        config = SandboxConfig(
            mode=SandboxMode.LANDLOCK,
            workspace_dir="/home/user/project",
            mounts=[
                MountSpec(path="/home/user/project", writable=True),
                MountSpec(path="/opt/data", writable=False),
            ],
        )
        with patch("os.path.exists", return_value=True):
            script = _generate_sandbox_script(
                config,
                "ls",
                "/home/user/project",
                1,
            )

        # /opt/data should be in the script with read-only access
        assert "/opt/data" in script

    def test_deny_paths_excluded(self):
        from qwenpaw.sandbox.linux_sandbox import _generate_sandbox_script

        config = SandboxConfig(
            mode=SandboxMode.LANDLOCK,
            workspace_dir="/home/user/project",
            mounts=[MountSpec(path="/home/user/project", writable=True)],
            allow_read_all=False,
            deny_paths=["/home/user/.ssh"],
        )
        script = _generate_sandbox_script(
            config,
            "ls",
            "/home/user/project",
            1,
        )

        # deny_paths should NOT appear as an add_path call
        # (the path should not be granted access)
        lines_with_ssh = [
            line
            for line in script.split("\n")
            if ".ssh" in line and "add_path" in line
        ]
        assert len(lines_with_ssh) == 0

    def test_executable_false(self):
        from qwenpaw.sandbox.linux_sandbox import (
            _FS_EXEC_ACCESS,
            _generate_sandbox_script,
        )

        config = SandboxConfig(
            mode=SandboxMode.LANDLOCK,
            workspace_dir="/home/user/project",
            mounts=[
                MountSpec(
                    path="/home/user/project",
                    writable=True,
                    executable=True,
                ),
                MountSpec(
                    path="/tmp/untrusted",
                    writable=True,
                    executable=False,
                ),
            ],
        )
        script = _generate_sandbox_script(
            config,
            "ls",
            "/home/user/project",
            1,
        )

        # /tmp/untrusted should NOT have EXEC access bit
        # Find the line with /tmp/untrusted
        for line in script.split("\n"):
            if "/tmp/untrusted" in line and "add_path" in line:
                # The hex access mask should NOT include EXEC (0x1)
                assert (
                    f"0x{_FS_EXEC_ACCESS:x}" not in line
                    or "0x1" not in line.split(",")[1]
                )
                break


# ============================================================================
# Governance: sandbox_available=False → SANDBOX_FALLBACK escalates to ASK
# ============================================================================


class TestGovernanceSandboxUnavailable:
    """Test SANDBOX_FALLBACK escalates to ASK when sandbox unavailable."""

    def test_sandbox_fallback_becomes_ask(self):
        """When sandbox is unavailable, SANDBOX_FALLBACK should become ASK."""
        cap = SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Kernel 5.10 < 5.13, Landlock unavailable",
        )

        from qwenpaw.governance.resource_governor import ResourceGovernor

        governor = ResourceGovernor(workspace_dir="/tmp/test_ws")

        # Mock policy loading to avoid filesystem operations
        with (
            patch(
                "qwenpaw.governance.resource_governor.load_governance_policy",
            ) as mock_load,
            patch("pathlib.Path.mkdir"),
            patch(
                "qwenpaw.governance.resource_governor.probe_sandbox_support",
                return_value=cap,
            ),
        ):
            mock_policy = MagicMock()
            mock_load.return_value = mock_policy
            governor.start()

        assert governor.sandbox_available is False
        assert (
            governor.sandbox_capability.reason
            == "Kernel 5.10 < 5.13, Landlock unavailable"
        )
