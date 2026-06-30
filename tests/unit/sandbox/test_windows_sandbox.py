# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access,unused-variable
"""Unit tests for Windows AppContainer sandbox."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from qwenpaw.sandbox import MountSpec, SandboxConfig, SandboxMode
from qwenpaw.sandbox.windows_sandbox import (
    _VIOLATION_RE,
    CRITICAL_SYSTEM_DIRS,
    WindowsSandbox,
    _compute_acl_fingerprint,
    _compute_network_capabilities,
    _create_workspace_junction,
    _find_reusable_container,
    _load_container_metadata,
    _save_container_metadata,
)

# ============================================================================
# ACL fingerprint tests
# ============================================================================


class TestACLFingerprint:
    """Test deterministic fingerprint computation."""

    def test_same_config_same_fingerprint(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            mounts=[MountSpec(path=r"C:\Users\foo\project", writable=True)],
            deny_paths=["~/.ssh", "~/.aws"],
            allow_read_all=True,
            network_allow=["*"],
        )
        fp1 = _compute_acl_fingerprint(config)
        fp2 = _compute_acl_fingerprint(config)
        assert fp1 == fp2

    def test_different_workspace_different_fingerprint(self):
        config1 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project1",
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project2",
        )
        assert _compute_acl_fingerprint(config1) != _compute_acl_fingerprint(
            config2
        )

    def test_different_deny_paths_different_fingerprint(self):
        config1 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            deny_paths=["~/.ssh"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            deny_paths=["~/.aws"],
        )
        assert _compute_acl_fingerprint(config1) != _compute_acl_fingerprint(
            config2
        )

    def test_order_independent(self):
        """Mount order and deny_path order should not affect fingerprint."""
        config1 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            mounts=[
                MountSpec(path=r"C:\a", writable=True),
                MountSpec(path=r"C:\b", writable=False),
            ],
            deny_paths=["~/.ssh", "~/.aws"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            mounts=[
                MountSpec(path=r"C:\b", writable=False),
                MountSpec(path=r"C:\a", writable=True),
            ],
            deny_paths=["~/.aws", "~/.ssh"],
        )
        assert _compute_acl_fingerprint(config1) == _compute_acl_fingerprint(
            config2
        )

    def test_fingerprint_is_16_chars(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
        )
        assert len(_compute_acl_fingerprint(config)) == 16


# ============================================================================
# Network capability tests
# ============================================================================


class TestNetworkCapabilities:
    """Test network capability computation from config."""

    def test_no_network_empty_list(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            network_allow=[],
        )
        assert _compute_network_capabilities(config) == []

    def test_no_network_default(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
        )
        # Default network_allow is [] (empty)
        assert _compute_network_capabilities(config) == []

    def test_full_network(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            network_allow=["*"],
        )
        caps = _compute_network_capabilities(config)
        assert "internetClient" in caps
        assert "internetClientServer" in caps
        assert "privateNetworkClientServer" in caps

    def test_domain_list_falls_back_to_all(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            network_allow=["example.com", "api.example.com"],
        )
        # Domain-level filtering not supported, falls back to all
        caps = _compute_network_capabilities(config)
        assert len(caps) == 3
        assert "internetClient" in caps


# ============================================================================
# Violation detection tests
# ============================================================================


class TestViolationDetection:
    """Test that access-denied patterns are correctly flagged."""

    def test_access_is_denied(self):
        assert _VIOLATION_RE.search("Access is denied")

    def test_error_5(self):
        assert _VIOLATION_RE.search("System error 5 has occurred")

    def test_hresult(self):
        assert _VIOLATION_RE.search("Failed with 0x80070005")

    def test_permission_denied(self):
        assert _VIOLATION_RE.search("Permission denied")

    def test_no_violation(self):
        assert _VIOLATION_RE.search("Command completed successfully") is None

    def test_case_insensitive(self):
        assert _VIOLATION_RE.search("ACCESS IS DENIED")


# ============================================================================
# Junction management tests
# ============================================================================


class TestJunctionPath:
    """Test junction path derivation."""

    @patch("subprocess.run")
    @patch("os.readlink")
    def test_creates_junction_when_not_exists(self, mock_readlink, mock_run):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            workspace = r"C:\Users\foo\project"

            mock_run.return_value = MagicMock(returncode=0)

            result = _create_workspace_junction(workspace, state_dir)

            assert "junctions" in result
            # mklink /J was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "mklink" in call_args
            assert "/J" in call_args

    @patch("os.path.exists", return_value=True)
    @patch("os.readlink")
    def test_reuses_existing_junction_with_correct_target(
        self, mock_readlink, mock_exists
    ):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            workspace = r"C:\Users\foo\project"

            # Create the junctions dir and a fake junction
            junction_dir = state_dir / "junctions"
            junction_dir.mkdir(parents=True)

            import hashlib

            ws_hash = hashlib.sha256(workspace.encode()).hexdigest()[:12]
            junction_path = junction_dir / ws_hash
            junction_path.mkdir()

            # readlink returns the correct target
            mock_readlink.return_value = workspace

            result = _create_workspace_junction(workspace, state_dir)
            assert result == str(junction_path)


# ============================================================================
# Sandbox reuse tests
# ============================================================================


class TestSandboxReuse:
    """Test container reuse logic."""

    def test_save_and_load_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            _save_container_metadata(
                state_dir,
                "qwenpaw_test123",
                "S-1-15-2-12345",
                "abcdef1234567890",
                r"C:\project",
                r"C:\Users\foo\.qwenpaw\junctions\abc",
            )

            loaded = _load_container_metadata(state_dir)
            assert len(loaded) == 1
            assert loaded[0]["container_name"] == "qwenpaw_test123"
            assert loaded[0]["sid"] == "S-1-15-2-12345"
            assert loaded[0]["acl_fingerprint"] == "abcdef1234567890"

    @patch(
        "qwenpaw.sandbox.windows_sandbox._get_appcontainer_sid",
        return_value="S-1-15-2-12345",
    )
    def test_find_reusable_container_match(self, mock_get_sid):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            _save_container_metadata(
                state_dir,
                "qwenpaw_test123",
                "S-1-15-2-12345",
                "abcdef1234567890",
                r"C:\project",
                r"C:\Users\foo\.qwenpaw\junctions\abc",
            )

            result = _find_reusable_container(state_dir, "abcdef1234567890")
            assert result is not None
            assert result["container_name"] == "qwenpaw_test123"

    @patch(
        "qwenpaw.sandbox.windows_sandbox._get_appcontainer_sid",
        return_value="S-1-15-2-12345",
    )
    def test_find_reusable_container_no_match(self, mock_get_sid):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            _save_container_metadata(
                state_dir,
                "qwenpaw_test123",
                "S-1-15-2-12345",
                "abcdef1234567890",
                r"C:\project",
                "",
            )

            result = _find_reusable_container(state_dir, "different_fp")
            assert result is None

    @patch(
        "qwenpaw.sandbox.windows_sandbox._get_appcontainer_sid",
        return_value=None,  # Container no longer exists
    )
    def test_find_reusable_container_stale(self, mock_get_sid):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            _save_container_metadata(
                state_dir,
                "qwenpaw_stale",
                "S-1-15-2-99999",
                "abcdef1234567890",
                r"C:\project",
                "",
            )

            result = _find_reusable_container(state_dir, "abcdef1234567890")
            assert result is None


# ============================================================================
# Probe function tests
# ============================================================================


class TestProbeAppContainer:
    """Test probe function under various Windows version scenarios."""

    @patch("sys.platform", "linux")
    def test_non_windows_returns_unsupported(self):
        from qwenpaw.sandbox.config import _probe_windows_appcontainer

        result = _probe_windows_appcontainer()
        assert result.supported is False
        assert "Not running on Windows" in result.reason

    @patch("sys.platform", "win32")
    def test_old_windows_returns_unsupported(self):
        import sys

        mock_ver = MagicMock(major=6, minor=3, build=9600)
        with patch.object(
            sys, "getwindowsversion", create=True, return_value=mock_ver
        ):
            from qwenpaw.sandbox.config import _probe_windows_appcontainer

            result = _probe_windows_appcontainer()
            assert result.supported is False
            assert "Windows 10+" in result.reason

    @patch("sys.platform", "win32")
    @patch("shutil.which", return_value=None)
    def test_no_icacls_returns_unsupported(self, mock_which):
        import sys

        mock_ver = MagicMock(major=10, minor=0, build=19045)
        with patch.object(
            sys, "getwindowsversion", create=True, return_value=mock_ver
        ):
            from qwenpaw.sandbox.config import _probe_windows_appcontainer

            result = _probe_windows_appcontainer()
            assert result.supported is False
            assert "icacls" in result.reason

    @patch("sys.platform", "win32")
    @patch("shutil.which", return_value=r"C:\Windows\System32\icacls.exe")
    def test_appcontainer_available(self, mock_which):
        import ctypes
        import sys

        mock_ver = MagicMock(major=10, minor=0, build=19045)
        mock_dll = MagicMock()
        mock_dll.CreateAppContainerProfile = MagicMock()

        with (
            patch.object(
                sys, "getwindowsversion", create=True, return_value=mock_ver
            ),
            patch.object(ctypes, "WinDLL", create=True, return_value=mock_dll),
        ):
            from qwenpaw.sandbox.config import _probe_windows_appcontainer

            result = _probe_windows_appcontainer()
            assert result.supported is True
            assert result.mode == SandboxMode.APPCONTAINER
            assert "AppContainer available" in result.reason


# ============================================================================
# WindowsSandbox execution tests (mocked)
# ============================================================================


class TestWindowsSandboxExecution:
    """Test WindowsSandbox.execute() with mocked Win32 API calls."""

    def _make_config(self):
        return SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
            mounts=[MountSpec(path=r"C:\Users\foo\project", writable=True)],
            deny_paths=["~/.ssh"],
            timeout_seconds=30,
            network_allow=["*"],
        )

    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    def test_execute_success(self, mock_wait, mock_create):
        config = self._make_config()
        sandbox = WindowsSandbox(config)
        sandbox._container_sid = "S-1-15-2-12345"
        sandbox._container_name = "qwenpaw_test"
        sandbox._junction_path = None

        mock_create.return_value = (1234, "handle", "stdout_h", "stderr_h")

        async def mock_wait_coro(*args, **kwargs):
            return (0, "hello world\n", "", False)

        mock_wait.side_effect = mock_wait_coro

        result = asyncio.run(sandbox.execute("echo hello world"))

        assert result.exit_code == 0
        assert result.stdout == "hello world\n"
        assert result.sandbox_violation is None
        assert result.timed_out is False

    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    def test_execute_violation(self, mock_wait, mock_create):
        config = self._make_config()
        sandbox = WindowsSandbox(config)
        sandbox._container_sid = "S-1-15-2-12345"
        sandbox._container_name = "qwenpaw_test"
        sandbox._junction_path = None

        mock_create.return_value = (1234, "handle", "stdout_h", "stderr_h")

        async def mock_wait_coro(*args, **kwargs):
            return (1, "", "Access is denied.\n", False)

        mock_wait.side_effect = mock_wait_coro

        result = asyncio.run(
            sandbox.execute("type C:\\Users\\foo\\.ssh\\id_rsa")
        )

        assert result.exit_code == 1
        assert result.sandbox_violation is not None
        assert "Access is denied" in result.sandbox_violation

    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    def test_execute_timeout(self, mock_wait, mock_create):
        config = self._make_config()
        config.timeout_seconds = 1
        sandbox = WindowsSandbox(config)
        sandbox._container_sid = "S-1-15-2-12345"
        sandbox._container_name = "qwenpaw_test"
        sandbox._junction_path = None

        mock_create.return_value = (1234, "handle", "stdout_h", "stderr_h")

        async def mock_wait_coro(*args, **kwargs):
            return (1, "", "Command timed out", True)

        mock_wait.side_effect = mock_wait_coro

        result = asyncio.run(sandbox.execute("timeout /t 100"))

        assert result.timed_out is True

    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_os_error(self, mock_create):
        config = self._make_config()
        sandbox = WindowsSandbox(config)
        sandbox._container_sid = "S-1-15-2-12345"
        sandbox._container_name = "qwenpaw_test"
        sandbox._junction_path = None

        mock_create.side_effect = OSError("CreateProcessW failed: error=5")

        result = asyncio.run(sandbox.execute("echo test"))

        assert result.exit_code == -1
        assert "CreateProcessW failed" in result.stderr


# ============================================================================
# Factory integration test
# ============================================================================


class TestFactoryAppContainer:
    """Test that create_sandbox correctly routes to WindowsSandbox."""

    def test_create_sandbox_appcontainer(self):
        from qwenpaw.sandbox import create_sandbox

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\foo\project",
        )
        sandbox = create_sandbox(config)
        assert isinstance(sandbox, WindowsSandbox)


# ============================================================================
# C:\Users directory workaround tests
# ============================================================================


class TestUsersDirectoryWorkaround:
    """Test the C:\\Users ACL inheritance fix logic."""

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_users_dir_gets_explicit_acl_when_allow_read_all(
        self, mock_exists, mock_isdir, mock_icacls
    ):
        """When allow_read_all=True, C:\\Users and USERPROFILE get explicit ACLs."""

        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\testuser\project",
            allow_read_all=True,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        # Verify icacls was called for C:\Users and C:\Users\testuser
        all_calls = mock_icacls.call_args_list
        all_paths = [call[0][0][0] for call in all_calls]
        assert r"C:\Users" in all_paths
        assert r"C:\Users\testuser" in all_paths

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=False)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_no_users_dir_acl_when_allow_read_all_false(
        self, mock_exists, mock_isdir, mock_icacls
    ):
        """When allow_read_all=False, no broad read ACLs are set."""

        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\Users\testuser\project",
            allow_read_all=False,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        # Verify icacls was NOT called with C:\ grant
        all_calls = mock_icacls.call_args_list
        all_args = [call[0][0] for call in all_calls]
        # No C:\ root grant
        root_grants = [
            a for a in all_args if a[0] == "C:\\" and "/grant" in a[1:]
        ]
        # The function only grants system dirs + workspace, not root
        for args in all_args:
            assert args[0] != "C:\\" or "/grant" not in " ".join(args)


# ============================================================================
# ACL command generation tests
# ============================================================================


class TestACLCommandGeneration:
    """Test that correct icacls commands are generated."""

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_deny_path_uses_deny_flag(
        self, mock_exists, mock_isdir, mock_icacls
    ):
        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            deny_paths=[r"C:\Users\testuser\.ssh"],
            allow_read_all=False,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        # Find the deny call
        all_calls = mock_icacls.call_args_list
        deny_calls = [
            call[0][0] for call in all_calls if "/deny" in call[0][0]
        ]
        assert len(deny_calls) == 1
        assert r"C:\Users\testuser\.ssh" in deny_calls[0]

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_workspace_gets_full_access(
        self, mock_exists, mock_isdir, mock_icacls
    ):
        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            allow_read_all=False,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        # Find workspace grant
        all_calls = mock_icacls.call_args_list
        workspace_calls = [
            call[0][0]
            for call in all_calls
            if call[0][0][0] == r"C:\project" and "/grant" in call[0][0]
        ]
        assert len(workspace_calls) == 1
        assert "(F)" in workspace_calls[0][2]  # Full access

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_readonly_mount_gets_rx(
        self, mock_exists, mock_isdir, mock_icacls
    ):
        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            mounts=[
                MountSpec(
                    path=r"C:\readonly_dir", writable=False, executable=True
                )
            ],
            allow_read_all=False,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        # Find mount grant
        all_calls = mock_icacls.call_args_list
        mount_calls = [
            call[0][0]
            for call in all_calls
            if len(call[0][0]) > 0 and call[0][0][0] == r"C:\readonly_dir"
        ]
        assert len(mount_calls) == 1
        assert "(RX)" in mount_calls[0][2]


# ============================================================================
# Config probe test (Windows)
# ============================================================================


class TestConfigProbeWindows:
    """Test probe_sandbox_support delegates to AppContainer probe on Windows."""

    @patch("sys.platform", "win32")
    @patch("qwenpaw.sandbox.config._probe_windows_appcontainer")
    def test_windows_calls_appcontainer_probe(self, mock_probe):
        from qwenpaw.sandbox.config import (
            SandboxCapability,
            probe_sandbox_support,
        )

        mock_probe.return_value = SandboxCapability(
            supported=True,
            mode=SandboxMode.APPCONTAINER,
            reason="AppContainer available",
        )
        result = probe_sandbox_support()
        mock_probe.assert_called_once()
        assert result.supported is True
        assert result.mode == SandboxMode.APPCONTAINER
