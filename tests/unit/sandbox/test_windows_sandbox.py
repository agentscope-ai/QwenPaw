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
    8. AppContainer profile creation / deletion lifecycle
    9. NTFS junction creation / removal
    10. WindowsSandbox.execute() — success / violation / timeout
    11. Cleanup script idempotency
"""

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
    _create_workspace_junction,
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
        assert not _compute_network_capabilities(config)

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


# ============================================================================
# AppContainer profile creation / deletion lifecycle
# ============================================================================


class TestAppContainerProfileLifecycle:
    """Test profile creation and deletion via mocked Win32 APIs."""

    @patch("qwenpaw.sandbox.windows_sandbox._sid_to_string")
    @patch("ctypes.windll", create=True)
    @patch("qwenpaw.sandbox.windows_sandbox._get_advapi32")
    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_create_profile_success(
        self,
        mock_userenv_fn,
        mock_advapi32_fn,
        mock_windll,
        mock_sid_to_str,
    ):
        """CreateAppContainerProfile returns 0 → SID is extracted."""
        mock_userenv = MagicMock()
        mock_userenv.CreateAppContainerProfile.return_value = 0
        mock_userenv_fn.return_value = mock_userenv

        mock_advapi32 = MagicMock()
        mock_advapi32_fn.return_value = mock_advapi32

        mock_windll.ole32.CoTaskMemFree = MagicMock()
        mock_sid_to_str.return_value = "S-1-15-2-111-222-333"

        from qwenpaw.sandbox.windows_sandbox import (
            _create_appcontainer_profile,
        )

        sid = _create_appcontainer_profile(
            "qwenpaw_test",
            "Test",
            "Test container",
        )
        assert sid == "S-1-15-2-111-222-333"
        mock_userenv.CreateAppContainerProfile.assert_called_once()
        mock_sid_to_str.assert_called_once()

    @patch("qwenpaw.sandbox.windows_sandbox._get_appcontainer_sid")
    @patch("qwenpaw.sandbox.windows_sandbox._get_advapi32")
    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_create_profile_already_exists(
        self,
        mock_userenv_fn,
        mock_advapi32_fn,
        mock_get_sid,
    ):
        """HRESULT 0x800700B7 (already exists) → derives SID instead."""
        mock_userenv = MagicMock()
        # _HRESULT_ERROR_ALREADY_EXISTS = -2147023649
        mock_userenv.CreateAppContainerProfile.return_value = -2147023649
        mock_userenv_fn.return_value = mock_userenv

        mock_get_sid.return_value = "S-1-15-2-999-888-777"

        from qwenpaw.sandbox.windows_sandbox import (
            _create_appcontainer_profile,
        )

        sid = _create_appcontainer_profile(
            "qwenpaw_existing",
            "Test",
            "Existing container",
        )
        assert sid == "S-1-15-2-999-888-777"
        mock_get_sid.assert_called_once_with("qwenpaw_existing")

    @patch("qwenpaw.sandbox.windows_sandbox._get_appcontainer_sid")
    @patch("qwenpaw.sandbox.windows_sandbox._get_advapi32")
    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_create_profile_already_exists_no_sid(
        self,
        mock_userenv_fn,
        mock_advapi32_fn,
        mock_get_sid,
    ):
        """Already exists but cannot derive SID → raises OSError."""
        mock_userenv = MagicMock()
        mock_userenv.CreateAppContainerProfile.return_value = -2147023649
        mock_userenv_fn.return_value = mock_userenv

        mock_get_sid.return_value = None

        import pytest

        from qwenpaw.sandbox.windows_sandbox import (
            _create_appcontainer_profile,
        )

        with pytest.raises(OSError, match="cannot derive SID"):
            _create_appcontainer_profile(
                "qwenpaw_broken",
                "Test",
                "Broken container",
            )

    @patch("qwenpaw.sandbox.windows_sandbox._get_advapi32")
    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_create_profile_unexpected_hresult(
        self,
        mock_userenv_fn,
        mock_advapi32_fn,
    ):
        """Unknown HRESULT → raises OSError."""
        mock_userenv = MagicMock()
        mock_userenv.CreateAppContainerProfile.return_value = -2147024891
        mock_userenv_fn.return_value = mock_userenv

        import pytest

        from qwenpaw.sandbox.windows_sandbox import (
            _create_appcontainer_profile,
        )

        with pytest.raises(OSError, match="CreateAppContainerProfile failed"):
            _create_appcontainer_profile(
                "qwenpaw_fail",
                "Test",
                "Failing container",
            )

    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_delete_profile_success(self, mock_userenv_fn):
        """DeleteAppContainerProfile returns 0 → True."""
        mock_userenv = MagicMock()
        mock_userenv.DeleteAppContainerProfile.return_value = 0
        mock_userenv_fn.return_value = mock_userenv

        from qwenpaw.sandbox.windows_sandbox import (
            _delete_appcontainer_profile,
        )

        assert _delete_appcontainer_profile("qwenpaw_test") is True

    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_delete_profile_failure(self, mock_userenv_fn):
        """DeleteAppContainerProfile returns non-zero → False."""
        mock_userenv = MagicMock()
        mock_userenv.DeleteAppContainerProfile.return_value = -1
        mock_userenv_fn.return_value = mock_userenv

        from qwenpaw.sandbox.windows_sandbox import (
            _delete_appcontainer_profile,
        )

        assert _delete_appcontainer_profile("qwenpaw_missing") is False

    @patch("qwenpaw.sandbox.windows_sandbox._get_userenv")
    def test_delete_profile_oserror(self, mock_userenv_fn):
        """OSError during delete → returns False."""
        mock_userenv = MagicMock()
        mock_userenv.DeleteAppContainerProfile.side_effect = OSError("fail")
        mock_userenv_fn.return_value = mock_userenv

        from qwenpaw.sandbox.windows_sandbox import (
            _delete_appcontainer_profile,
        )

        assert _delete_appcontainer_profile("qwenpaw_err") is False


# ============================================================================
# NTFS junction creation / removal
# ============================================================================


class TestNTFSJunction:
    """Test NTFS junction creation and fallback behavior."""

    def test_create_junction_new(self):
        """Creates a junction when none exists."""
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            workspace = str(state_dir / "workspace")
            os.makedirs(workspace)

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = _create_workspace_junction(workspace, state_dir)

            # Should be under state_dir/junctions/<hash>
            assert "junctions" in result
            mock_run.assert_called_once()
            cmd_args = mock_run.call_args[0][0]
            assert "mklink" in cmd_args
            assert "/J" in cmd_args

    def test_create_junction_existing_correct_target(self):
        """Reuses existing junction if it points to the correct target."""
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            workspace = str(state_dir / "workspace")
            os.makedirs(workspace)

            # Pre-create the junction directory (simulate existing junction)
            import hashlib

            ws_hash = hashlib.sha256(workspace.encode()).hexdigest()[:12]
            junction_dir = state_dir / "junctions"
            junction_dir.mkdir(parents=True)
            junction_path = junction_dir / ws_hash
            # Create as a directory (like a real junction)
            junction_path.mkdir()

            # Mock os.readlink to return the workspace path (simulates a
            # correctly-targeted junction without an actual NTFS junction)
            with (
                patch("os.readlink", return_value=workspace),
                patch("subprocess.run") as mock_run,
            ):
                result = _create_workspace_junction(workspace, state_dir)

            mock_run.assert_not_called()
            assert result == str(junction_path)

    def test_create_junction_failure_falls_back(self):
        """Falls back to workspace_dir if mklink fails."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            workspace = str(state_dir / "workspace")
            os.makedirs(workspace)

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(
                    1,
                    "cmd",
                    stderr=b"error",
                )
                result = _create_workspace_junction(workspace, state_dir)

            # Falls back to workspace path
            assert result == workspace


# ============================================================================
# WindowsSandbox.execute() — success / violation / timeout
# ============================================================================


class TestWindowsSandboxExecute:
    """Test execute() method with mocked process creation."""

    def _make_sandbox(self, **kwargs):
        defaults = {
            "mode": SandboxMode.APPCONTAINER,
            "workspace_dir": r"C:\project",
        }
        defaults.update(kwargs)
        config = SandboxConfig(**defaults)
        sandbox = WindowsSandbox(config)
        sandbox._container_sid = "S-1-15-2-12345"
        sandbox._container_name = "qwenpaw_test"
        sandbox._junction_path = None
        return sandbox

    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_success(self, mock_create, mock_wait):
        """Successful command returns exit_code=0, no violation."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        async def fake_wait(*args):
            return (0, "hello world\n", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("echo hello world"))

        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert result.sandbox_violation is None
        assert result.timed_out is False

    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_violation_detected(self, mock_create, mock_wait):
        """Access denied in stderr → sandbox_violation is populated."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        async def fake_wait(*args):
            return (1, "", "Access is denied\n", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("type C:\\secret.txt"))

        assert result.exit_code == 1
        assert result.sandbox_violation is not None
        assert "Access is denied" in result.sandbox_violation

    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_timeout(self, mock_create, mock_wait):
        """Process exceeds timeout → timed_out=True."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        async def fake_wait(*args):
            return (1, "", "", True)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox(timeout_seconds=5)
        result = asyncio.run(sandbox.execute("ping -n 100 127.0.0.1"))

        assert result.timed_out is True

    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_oserror(self, mock_create, mock_wait):
        """CreateProcessW failure → exit_code=-1, error in stderr."""
        mock_create.side_effect = OSError("CreateProcessW failed: error=5")

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("whoami"))

        assert result.exit_code == -1
        assert "CreateProcessW failed" in result.stderr

    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_violation_in_stdout_on_failure(
        self,
        mock_create,
        mock_wait,
    ):
        """Violation pattern in stdout (with non-zero exit) is detected."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        async def fake_wait(*args):
            return (1, "error 5 occurred\n", "", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("del C:\\protected\\file.txt"))

        assert result.sandbox_violation is not None
        assert "error 5" in result.sandbox_violation

    @patch("qwenpaw.sandbox.windows_sandbox._wait_and_read_process")
    @patch("qwenpaw.sandbox.windows_sandbox._create_process_in_appcontainer")
    def test_execute_chinese_violation(self, mock_create, mock_wait):
        """Chinese locale violation patterns are detected."""
        mock_create.return_value = (
            1234,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        async def fake_wait(*args):
            return (1, "", "\u62d2\u7edd\u8bbf\u95ee\u3002\n", False)

        mock_wait.side_effect = fake_wait

        sandbox = self._make_sandbox()
        result = asyncio.run(sandbox.execute("dir C:\\secret"))

        assert result.sandbox_violation is not None
