# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Unit tests for Linux bubblewrap sandbox."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.sandbox import (
    MountSpec,
    SandboxCapability,
    SandboxConfig,
    SandboxMode,
    create_sandbox,
)
from qwenpaw.sandbox.bubblewrap_sandbox import (
    BubblewrapSandbox,
    _BWRAP_VIOLATION_RE,
)
from qwenpaw.sandbox.config import _probe_linux_bubblewrap


# ============================================================================
# _build_bwrap_args() — parameter generation
# ============================================================================


class TestBuildBwrapArgs:
    """Test bwrap command-line argument generation."""

    def _make_sandbox(self, **kwargs) -> BubblewrapSandbox:
        defaults = {
            "mode": SandboxMode.BUBBLEWRAP,
            "workspace_dir": "/tmp/ws",
        }
        defaults.update(kwargs)
        config = SandboxConfig(**defaults)
        return BubblewrapSandbox(config)

    def test_allow_read_all_generates_ro_bind_root(self):
        sb = self._make_sandbox(allow_read_all=True)
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        assert "--ro-bind" in args
        # Verify the root bind: --ro-bind / /
        idx = args.index("--ro-bind")
        assert args[idx + 1] == "/"
        assert args[idx + 2] == "/"

    def test_allow_read_all_false_generates_tmpfs_root(self):
        sb = self._make_sandbox(allow_read_all=False)
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        # First filesystem arg should be --tmpfs /
        idx = args.index("--tmpfs")
        assert args[idx + 1] == "/"

    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=True)
    def test_deny_paths_generate_tmpfs_for_dirs(self, mock_isdir, mock_exists):
        sb = self._make_sandbox(deny_paths=["/home/user/.ssh"])
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        # Find --tmpfs for the deny_path
        tmpfs_indices = [i for i, x in enumerate(args) if x == "--tmpfs"]
        deny_found = any(
            args[i + 1] == "/home/user/.ssh" for i in tmpfs_indices
        )
        assert deny_found, f"deny_path not masked with --tmpfs, args={args}"

    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=False)
    def test_deny_paths_generate_ro_bind_devnull_for_files(
        self,
        mock_isdir,
        mock_exists,
    ):
        sb = self._make_sandbox(deny_paths=["/etc/secret.conf"])
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        # Should bind /dev/null over the file
        for i, x in enumerate(args):
            if x == "--ro-bind" and i + 2 < len(args):
                if args[i + 2] == "/etc/secret.conf":
                    assert args[i + 1] == "/dev/null"
                    break
        else:
            pytest.fail(
                f"deny_path file not masked with /dev/null, args={args}",
            )

    @patch("os.path.exists", return_value=True)
    @patch("os.path.isdir", return_value=True)
    def test_writable_mount_generates_bind(self, mock_isdir, mock_exists):
        sb = self._make_sandbox(
            mounts=[MountSpec(path="/workspace/project", writable=True)],
        )
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        # Find --bind for writable mount
        bind_indices = [i for i, x in enumerate(args) if x == "--bind"]
        writable_found = any(
            args[i + 1] == "/workspace/project" for i in bind_indices
        )
        assert writable_found, f"writable mount not found, args={args}"

    def test_dev_always_present(self):
        sb = self._make_sandbox()
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        assert "--dev" in args
        idx = args.index("--dev")
        assert args[idx + 1] == "/dev"

    def test_unshare_pid_and_user(self):
        sb = self._make_sandbox()
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        assert "--unshare-user" in args
        assert "--unshare-pid" in args

    def test_proc_mount(self):
        sb = self._make_sandbox()
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        assert "--proc" in args
        idx = args.index("--proc")
        assert args[idx + 1] == "/proc"

    def test_command_at_end(self):
        sb = self._make_sandbox()
        args = sb._build_bwrap_args("echo hello", "/tmp/ws")
        # Should end with: -- <shell> -c <cmd>
        assert "--" in args
        separator_idx = args.index("--")
        # After -- there should be: shell, -c, cmd
        remaining = args[separator_idx + 1 :]
        assert remaining[-2] == "-c"
        assert remaining[-1] == "echo hello"

    @patch("os.path.isdir", return_value=True)
    def test_chdir_when_cwd_valid(self, mock_isdir):
        sb = self._make_sandbox()
        args = sb._build_bwrap_args("ls", "/workspace")
        assert "--chdir" in args
        idx = args.index("--chdir")
        assert args[idx + 1] == "/workspace"

    def test_new_session_and_die_with_parent(self):
        sb = self._make_sandbox()
        args = sb._build_bwrap_args("echo hi", "/tmp/ws")
        assert "--new-session" in args
        assert "--die-with-parent" in args


# ============================================================================
# Violation detection regex
# ============================================================================


class TestBwrapViolationRegex:
    """Test violation detection regex patterns."""

    def test_permission_denied(self):
        assert _BWRAP_VIOLATION_RE.search("Permission denied")

    def test_bwrap_error_prefix(self):
        assert _BWRAP_VIOLATION_RE.search("bwrap: No such file or directory")

    def test_operation_not_permitted(self):
        assert _BWRAP_VIOLATION_RE.search("Operation not permitted")

    def test_eacces(self):
        assert _BWRAP_VIOLATION_RE.search("open failed: EACCES")

    def test_normal_output_no_match(self):
        assert _BWRAP_VIOLATION_RE.search("hello world") is None

    def test_partial_word_no_match(self):
        # "Permission denied" should match as whole word boundary
        assert _BWRAP_VIOLATION_RE.search("PermissionDenied") is None


# ============================================================================
# Probe logic
# ============================================================================


class TestProbeLinuxBubblewrap:
    """Test _probe_linux_bubblewrap() probe function."""

    @patch("shutil.which", return_value=None)
    def test_bwrap_not_found(self, mock_which):
        result = _probe_linux_bubblewrap()
        assert result.supported is False
        assert result.mode == SandboxMode.NONE
        assert "not found" in result.reason

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    @patch("subprocess.run")
    def test_bwrap_probe_success(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _probe_linux_bubblewrap()
        assert result.supported is True
        assert result.mode == SandboxMode.BUBBLEWRAP
        assert "bubblewrap available" in result.reason

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    @patch("subprocess.run")
    def test_bwrap_probe_fails_nonzero(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=b"bwrap: No permissions for user namespace",
        )
        result = _probe_linux_bubblewrap()
        assert result.supported is False
        assert result.mode == SandboxMode.NONE

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    @patch("subprocess.run", side_effect=OSError("exec failed"))
    def test_bwrap_probe_oserror(self, mock_run, mock_which):
        result = _probe_linux_bubblewrap()
        assert result.supported is False
        assert "error" in result.reason.lower()


# ============================================================================
# probe_sandbox_support — Linux routing (bwrap > landlock > none)
# ============================================================================


class TestProbeSandboxSupportLinuxBwrap:
    """Test that probe_sandbox_support on Linux tries bwrap first."""

    @patch("sys.platform", "linux")
    @patch(
        "qwenpaw.sandbox.config._probe_linux_bubblewrap",
        return_value=SandboxCapability(
            supported=True,
            mode=SandboxMode.BUBBLEWRAP,
            reason="bubblewrap available with user namespaces",
        ),
    )
    @patch("qwenpaw.sandbox.config._probe_linux_landlock")
    def test_bwrap_available_skips_landlock(
        self,
        mock_landlock,
        mock_bwrap,
    ):
        from qwenpaw.sandbox import probe_sandbox_support

        result = probe_sandbox_support()
        assert result.mode == SandboxMode.BUBBLEWRAP
        mock_landlock.assert_not_called()

    @patch("sys.platform", "linux")
    @patch(
        "qwenpaw.sandbox.config._probe_linux_bubblewrap",
        return_value=SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="bwrap not found on PATH",
        ),
    )
    @patch(
        "qwenpaw.sandbox.config._probe_linux_landlock",
        return_value=SandboxCapability(
            supported=True,
            mode=SandboxMode.LANDLOCK,
            reason="Kernel 6.5, Landlock ABI v4",
            landlock_abi_version=4,
        ),
    )
    def test_bwrap_unavailable_falls_to_landlock(
        self,
        mock_landlock,
        mock_bwrap,
    ):
        from qwenpaw.sandbox import probe_sandbox_support

        result = probe_sandbox_support()
        assert result.mode == SandboxMode.LANDLOCK


# ============================================================================
# Factory — create_sandbox()
# ============================================================================


class TestCreateSandboxBubblewrap:
    """Test create_sandbox returns BubblewrapSandbox for BUBBLEWRAP mode."""

    def test_create_sandbox_bubblewrap(self):
        config = SandboxConfig(
            mode=SandboxMode.BUBBLEWRAP,
            workspace_dir="/tmp/ws",
        )
        sb = create_sandbox(config)
        assert isinstance(sb, BubblewrapSandbox)

    def test_create_sandbox_unknown_mode_raises(self):
        config = SandboxConfig(
            mode=SandboxMode.BUBBLEWRAP,
            workspace_dir="/tmp/ws",
        )
        # Temporarily force an invalid mode
        config.mode = "bogus_mode"
        with pytest.raises(ValueError, match="Unknown sandbox mode"):
            create_sandbox(config)
