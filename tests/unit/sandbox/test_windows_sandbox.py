# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access,unused-variable
"""Unit tests for Windows AppContainer sandbox.

Test structure aligns with test_linux_sandbox.py:
    1. Platform routing (probe_sandbox_support dispatches correctly)
    2. Detailed probe logic (Windows version, icacls, WinDLL)
    3. ACL rule compilation (correct icacls commands generated)
    4. Violation detection regex
    5. Network capabilities (Windows-specific)
    6. Container reuse (Windows-specific)
    7. Factory (create_sandbox routing)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from qwenpaw.sandbox import MountSpec, SandboxConfig, SandboxMode
from qwenpaw.sandbox.windows_sandbox import (
    _VIOLATION_RE,
    WindowsSandbox,
    _compute_acl_fingerprint,
    _compute_network_capabilities,
    _find_reusable_container,
    _load_container_metadata,
    _save_container_metadata,
)

# ============================================================================
# probe_sandbox_support() — platform routing
# ============================================================================


class TestProbeSandboxSupport:
    """Test probe_sandbox_support delegates to AppContainer probe."""

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


# ============================================================================
# _probe_windows_appcontainer() — detailed probe logic
# ============================================================================


class TestProbeAppContainer:
    """Test AppContainer probe under various Windows version scenarios."""

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
            sys,
            "getwindowsversion",
            create=True,
            return_value=mock_ver,
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
            sys,
            "getwindowsversion",
            create=True,
            return_value=mock_ver,
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
                sys,
                "getwindowsversion",
                create=True,
                return_value=mock_ver,
            ),
            patch.object(ctypes, "WinDLL", create=True, return_value=mock_dll),
        ):
            from qwenpaw.sandbox.config import _probe_windows_appcontainer

            result = _probe_windows_appcontainer()
            assert result.supported is True
            assert result.mode == SandboxMode.APPCONTAINER
            assert "AppContainer available" in result.reason


# ============================================================================
# ACL rule compilation — correct icacls commands generated
# ============================================================================


class TestACLCommandGeneration:
    """Test that _apply_all_acls generates correct icacls commands.

    Analogous to TestLinuxSandboxRuleCompilation in test_linux_sandbox.py.
    """

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_workspace_gets_full_access(
        self,
        mock_exists,
        mock_isdir,
        mock_icacls,
    ):
        """Workspace directory receives (F) grant."""

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

        all_calls = mock_icacls.call_args_list
        workspace_calls = [
            call[0][0]
            for call in all_calls
            if call[0][0][0] == r"C:\project" and "/grant" in call[0][0]
        ]
        assert len(workspace_calls) == 1
        assert "(F)" in workspace_calls[0][2]

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_readonly_mount_gets_rx(
        self,
        mock_exists,
        mock_isdir,
        mock_icacls,
    ):
        """Read-only mount gets RX with inheritance break."""

        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            mounts=[
                MountSpec(
                    path=r"C:\readonly_dir",
                    writable=False,
                    executable=True,
                ),
            ],
            allow_read_all=False,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        # _break_and_set_acl produces 3 calls: /inheritance:d, /remove, /grant
        all_calls = mock_icacls.call_args_list
        mount_calls = [
            call[0][0]
            for call in all_calls
            if len(call[0][0]) > 0 and call[0][0][0] == r"C:\readonly_dir"
        ]
        assert len(mount_calls) == 3
        assert "/inheritance:d" in mount_calls[0]
        assert "/remove" in mount_calls[1]
        assert "(RX)" in mount_calls[2][2]

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_deny_path_uses_deny_flag(
        self,
        mock_exists,
        mock_isdir,
        mock_icacls,
    ):
        """Deny paths get /deny ACE with inheritance break."""

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
    def test_allow_read_all_grants_system_drive(
        self,
        mock_exists,
        mock_isdir,
        mock_icacls,
    ):
        """allow_read_all=True grants RX on C:\\, C:\\Users, USERPROFILE."""

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

        all_calls = mock_icacls.call_args_list
        all_paths = [call[0][0][0] for call in all_calls]
        assert "C:\\" in all_paths
        assert r"C:\Users" in all_paths
        assert r"C:\Users\testuser" in all_paths

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=False)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_no_system_drive_grant_when_allow_read_all_false(
        self,
        mock_exists,
        mock_isdir,
        mock_icacls,
    ):
        """allow_read_all=False does not grant C:\\ root."""

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

        all_calls = mock_icacls.call_args_list
        all_args = [call[0][0] for call in all_calls]
        for args in all_args:
            assert args[0] != "C:\\" or "/grant" not in " ".join(args)

    @patch("qwenpaw.sandbox.windows_sandbox._run_icacls")
    @patch("os.path.isdir", return_value=True)
    @patch("os.path.exists", return_value=True)
    @patch.dict(
        os.environ,
        {"SystemDrive": "C:", "USERPROFILE": r"C:\Users\testuser"},
    )
    def test_apply_all_acls_returns_manifest(
        self,
        mock_exists,
        mock_isdir,
        mock_icacls,
    ):
        """_apply_all_acls returns a manifest of all modified paths."""

        async def fake_icacls(args):
            return True, ""

        mock_icacls.side_effect = fake_icacls

        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            mounts=[MountSpec(path=r"C:\data", writable=False)],
            deny_paths=[r"C:\Users\testuser\.ssh"],
            allow_read_all=True,
        )

        from qwenpaw.sandbox.windows_sandbox import _apply_all_acls

        manifest = asyncio.run(_apply_all_acls(config, "S-1-15-2-12345"))

        assert "grant_paths" in manifest
        assert "inheritance_broken_paths" in manifest
        assert r"C:\project" in manifest["grant_paths"]
        assert "C:\\" in manifest["grant_paths"]
        assert r"C:\data" in manifest["inheritance_broken_paths"]
        broken = manifest["inheritance_broken_paths"]
        assert r"C:\Users\testuser\.ssh" in broken


# ============================================================================
# Violation detection regex
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
# Network capabilities (Windows-specific)
# ============================================================================


class TestNetworkCapabilities:
    """Test network capability computation from config."""

    def test_no_network_returns_empty(self):
        config = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            network_allow=[],
        )
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
        caps = _compute_network_capabilities(config)
        assert len(caps) == 3
        assert "internetClient" in caps


# ============================================================================
# Container reuse (Windows-specific)
# ============================================================================


class TestSandboxReuse:
    """Test container metadata persistence and reuse logic."""

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

    def test_save_and_load_metadata_with_acl_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            acl_manifest = {
                "grant_paths": [
                    "C:\\",
                    r"C:\Users",
                    r"C:\project",
                ],
                "inheritance_broken_paths": [
                    r"C:\Users\testuser\.ssh",
                    r"D:\shared_mount",
                ],
            }

            _save_container_metadata(
                state_dir,
                "qwenpaw_test456",
                "S-1-15-2-67890",
                "fedcba0987654321",
                r"C:\project",
                r"C:\Users\testuser\.qwenpaw\junctions\abc",
                acl_manifest,
            )

            loaded = _load_container_metadata(state_dir)
            assert len(loaded) == 1
            assert "acl_manifest" in loaded[0]
            manifest = loaded[0]["acl_manifest"]
            assert manifest["grant_paths"] == acl_manifest["grant_paths"]
            assert (
                manifest["inheritance_broken_paths"]
                == acl_manifest["inheritance_broken_paths"]
            )

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
        return_value=None,
    )
    def test_find_reusable_container_stale(self, mock_get_sid):
        """Container profile deleted externally → not reused."""
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

    def test_fingerprint_deterministic(self):
        """Same config produces same fingerprint; different config differs."""
        config1 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            deny_paths=["~/.ssh"],
        )
        config2 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\project",
            deny_paths=["~/.ssh"],
        )
        config3 = SandboxConfig(
            mode=SandboxMode.APPCONTAINER,
            workspace_dir=r"C:\other",
            deny_paths=["~/.ssh"],
        )
        assert _compute_acl_fingerprint(config1) == _compute_acl_fingerprint(
            config2,
        )
        assert _compute_acl_fingerprint(config1) != _compute_acl_fingerprint(
            config3,
        )
        assert len(_compute_acl_fingerprint(config1)) == 16


# ============================================================================
# Factory (create_sandbox routing)
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
