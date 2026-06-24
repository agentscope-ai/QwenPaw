# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access,unused-variable
"""Unit tests for Windows WSL2 sandbox."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from qwenpaw.sandbox import MountSpec, SandboxConfig, SandboxMode
from qwenpaw.sandbox.windows_sandbox import (
    WindowsSandbox,
    _generate_wsl_sandbox_script,
    probe_wsl2_availability,
    win_to_wsl_path,
    wsl_to_win_path,
)

# ============================================================================
# Path translation tests
# ============================================================================


class TestPathTranslation:
    """Test Windows ↔ WSL path conversion."""

    def test_win_to_wsl_c_drive(self):
        assert (
            win_to_wsl_path("C:\\Users\\foo\\project")
            == "/mnt/c/Users/foo/project"
        )

    def test_win_to_wsl_d_drive(self):
        assert win_to_wsl_path("D:\\data\\files") == "/mnt/d/data/files"

    def test_win_to_wsl_lowercase_drive(self):
        assert win_to_wsl_path("c:\\temp") == "/mnt/c/temp"

    def test_win_to_wsl_forward_slashes(self):
        assert win_to_wsl_path("C:/Users/foo") == "/mnt/c/Users/foo"

    def test_win_to_wsl_tilde(self):
        assert win_to_wsl_path("~/foo") == "~/foo"

    def test_win_to_wsl_tilde_only(self):
        assert win_to_wsl_path("~") == "~"

    def test_win_to_wsl_relative_path(self):
        assert win_to_wsl_path("relative/path") == "relative/path"

    def test_wsl_to_win_mnt_c(self):
        assert wsl_to_win_path("/mnt/c/Users/foo") == "C:\\Users\\foo"

    def test_wsl_to_win_mnt_d(self):
        assert wsl_to_win_path("/mnt/d/data") == "D:\\data"

    def test_wsl_to_win_non_mnt(self):
        # Non-/mnt paths are returned as-is
        assert wsl_to_win_path("/home/user/.ssh") == "/home/user/.ssh"


# ============================================================================
# WSL2 probe tests
# ============================================================================


class TestProbeWSL2:
    """Test WSL2 availability probing."""

    @patch("shutil.which", return_value=None)
    def test_wsl_not_found(self, mock_which):
        available, distro, reason = probe_wsl2_availability()
        assert available is False
        assert "not found" in reason

    @patch("shutil.which", return_value="C:\\Windows\\System32\\wsl.exe")
    @patch("subprocess.run")
    def test_wsl_no_distro(self, mock_run, mock_which):
        # First call: --status (ok)
        # Second call: --list --verbose (no WSL2 distros)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(
                returncode=0,
                stdout="NAME   STATE   VERSION\n",
                stderr="",
            ),
        ]
        available, distro, reason = probe_wsl2_availability()
        assert available is False
        assert "No WSL2" in reason

    @patch("shutil.which", return_value="C:\\Windows\\System32\\wsl.exe")
    @patch("subprocess.run")
    def test_wsl2_distro_found(self, mock_run, mock_which):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(
                returncode=0,
                stdout=(
                    "  NAME            STATE           VERSION\n"
                    "* Ubuntu-22.04    Running         2\n"
                ),
                stderr="",
            ),
        ]
        available, distro, reason = probe_wsl2_availability()
        assert available is True
        assert distro == "Ubuntu-22.04"


# ============================================================================
# Script generation tests
# ============================================================================


class TestWSLScriptGeneration:
    """Test Landlock enforcement script generation for WSL."""

    def test_basic_script_generation(self):
        config = SandboxConfig(
            mode=SandboxMode.WSL2,
            workspace_dir="C:\\Users\\foo\\project",
            mounts=[MountSpec(path="C:\\Users\\foo\\project", writable=True)],
        )
        script = _generate_wsl_sandbox_script(
            config,
            "echo hello",
            "/mnt/c/Users/foo/project",
            1,
            "/home/foo",
        )
        assert "add_path" in script
        assert "/mnt/c/Users/foo/project" in script
        assert "echo hello" in script
        assert "prctl" in script

    def test_deny_paths_excluded(self):
        config = SandboxConfig(
            mode=SandboxMode.WSL2,
            workspace_dir="C:\\Users\\foo\\project",
            mounts=[MountSpec(path="C:\\Users\\foo\\project", writable=True)],
            allow_read_all=True,
            deny_paths=["~/.ssh", "~/.aws"],
        )
        script = _generate_wsl_sandbox_script(
            config,
            "ls",
            "/mnt/c/Users/foo/project",
            1,
            "/home/foo",
        )
        # deny_paths should NOT appear as static add_path calls
        # but should appear in dynamic enumeration exclusion
        assert "/home/foo/.ssh" not in script.split("_deny_set", maxsplit=1)[0]
        assert "_deny_set" in script  # Dynamic home enumeration

    def test_no_deny_paths(self):
        config = SandboxConfig(
            mode=SandboxMode.WSL2,
            workspace_dir="C:\\Users\\foo\\project",
            mounts=[MountSpec(path="C:\\Users\\foo\\project", writable=True)],
            allow_read_all=True,
            deny_paths=[],
        )
        script = _generate_wsl_sandbox_script(
            config,
            "ls",
            "/mnt/c/Users/foo/project",
            1,
            "/home/foo",
        )
        # Should grant /mnt and home without dynamic enumeration
        assert "/mnt" in script
        assert "_deny_set" not in script


# ============================================================================
# WindowsSandbox execution tests (mocked)
# ============================================================================


class TestWindowsSandboxExecution:
    """Test WindowsSandbox.execute() with mocked WSL calls."""

    def _make_config(self):
        return SandboxConfig(
            mode=SandboxMode.WSL2,
            workspace_dir="C:\\Users\\foo\\project",
            mounts=[MountSpec(path="C:\\Users\\foo\\project", writable=True)],
            deny_paths=["~/.ssh"],
            timeout_seconds=30,
        )

    def test_execute_success(self):
        sandbox_config = self._make_config()
        sandbox = WindowsSandbox(sandbox_config, distro="Ubuntu-22.04")
        sandbox._wsl_home = "/home/foo"
        sandbox._abi_version = 3

        # Mock asyncio.create_subprocess_exec
        mock_write_proc = AsyncMock()
        mock_write_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_write_proc.returncode = 0

        mock_exec_proc = AsyncMock()
        mock_exec_proc.communicate = AsyncMock(
            return_value=(b"hello world\n", b""),
        )
        mock_exec_proc.returncode = 0

        mock_cleanup_proc = AsyncMock()
        mock_cleanup_proc.communicate = AsyncMock(return_value=(b"", b""))

        call_count = [0]

        async def mock_create_subprocess(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_write_proc
            elif call_count[0] == 2:
                return mock_exec_proc
            else:
                return mock_cleanup_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_create_subprocess,
        ):
            result = asyncio.run(sandbox.execute("echo hello world"))

        assert result.exit_code == 0
        assert result.stdout == "hello world\n"
        assert result.sandbox_violation is None

    def test_execute_violation(self):
        sandbox_config = self._make_config()
        sandbox = WindowsSandbox(sandbox_config, distro="Ubuntu-22.04")
        sandbox._wsl_home = "/home/foo"
        sandbox._abi_version = 3

        mock_write_proc = AsyncMock()
        mock_write_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_write_proc.returncode = 0

        mock_exec_proc = AsyncMock()
        mock_exec_proc.communicate = AsyncMock(
            return_value=(
                b"",
                b"cat: /home/foo/.ssh/id_rsa: Permission denied\n",
            ),
        )
        mock_exec_proc.returncode = 1

        mock_cleanup_proc = AsyncMock()
        mock_cleanup_proc.communicate = AsyncMock(return_value=(b"", b""))

        call_count = [0]

        async def mock_create_subprocess(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_write_proc
            elif call_count[0] == 2:
                return mock_exec_proc
            else:
                return mock_cleanup_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_create_subprocess,
        ):
            result = asyncio.run(sandbox.execute("cat ~/.ssh/id_rsa"))

        assert result.exit_code == 1
        assert result.sandbox_violation is not None
        assert "Permission denied" in result.sandbox_violation

    def test_execute_timeout(self):
        sandbox_config = self._make_config()
        sandbox_config.timeout_seconds = 1
        sandbox = WindowsSandbox(sandbox_config, distro="Ubuntu-22.04")
        sandbox._wsl_home = "/home/foo"
        sandbox._abi_version = 3

        mock_write_proc = AsyncMock()
        mock_write_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_write_proc.returncode = 0

        mock_exec_proc = AsyncMock()
        mock_exec_proc.communicate = AsyncMock(
            side_effect=asyncio.TimeoutError(),
        )
        mock_exec_proc.returncode = None
        mock_exec_proc.kill = MagicMock()

        call_count = [0]

        async def mock_create_subprocess(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_write_proc
            else:
                return mock_exec_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_create_subprocess,
        ):
            result = asyncio.run(sandbox.execute("sleep 100"))

        assert result.timed_out is True
        assert result.exit_code == -1


# ============================================================================
# Factory integration test
# ============================================================================


class TestFactoryWSL2:
    """Test that create_sandbox correctly routes to WindowsSandbox."""

    def test_create_sandbox_wsl2(self):
        from qwenpaw.sandbox import create_sandbox

        config = SandboxConfig(
            mode=SandboxMode.WSL2,
            workspace_dir="C:\\Users\\foo\\project",
        )
        sandbox = create_sandbox(config)
        assert isinstance(sandbox, WindowsSandbox)


# ============================================================================
# Config probe test (Windows)
# ============================================================================


class TestConfigProbeWindows:
    """Test probe_sandbox_support disables Windows sandbox at probe time."""

    @patch("sys.platform", "win32")
    @patch("qwenpaw.sandbox.config._probe_windows_wsl2")
    def test_windows_disabled_returns_none(self, mock_probe):
        from qwenpaw.sandbox.config import probe_sandbox_support

        # Windows sandbox is currently disabled at probe time — it should
        # NOT call ``_probe_windows_wsl2`` and should return ``mode=NONE``.
        result = probe_sandbox_support()
        assert result.supported is False
        assert result.mode == SandboxMode.NONE
        assert "disabled" in result.reason.lower()
        mock_probe.assert_not_called()
