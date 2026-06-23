# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for sandbox config and seatbelt profile generation."""

from __future__ import annotations

from unittest.mock import patch

from qwenpaw.sandbox import (
    MountSpec,
    PortRule,
    SandboxConfig,
    SandboxMode,
)
from qwenpaw.sandbox.macos_sandbox import MacOSSandbox

# ============================================================================
# Task 5.1: test_sandbox_config_defaults
# ============================================================================


class TestSandboxConfigDefaults:
    """Verify all new fields have correct default values."""

    def test_sandbox_config_defaults(self):
        config = SandboxConfig(
            mode=SandboxMode.SEATBELT,
            workspace_dir="/tmp/ws",
        )
        assert config.allow_read_all is True
        assert config.deny_paths == []
        assert config.network_allow == []
        assert config.network_ports is None
        assert config.max_processes is None
        assert config.max_memory_mb is None
        assert config.timeout_seconds == 30
        assert config.env_vars == {}
        assert config.env_mode == "inject"
        assert config.platform_hints == {}

    def test_mount_spec_executable_default(self):
        mount = MountSpec(path="/foo")
        assert mount.writable is False
        assert mount.executable is True

    def test_mount_spec_executable_false(self):
        mount = MountSpec(path="/foo", writable=True, executable=False)
        assert mount.writable is True
        assert mount.executable is False

    def test_port_rule_defaults(self):
        rule = PortRule(port=8080)
        assert rule.port == 8080
        assert rule.direction == "connect"
        assert rule.allow is True


# ============================================================================
# Task 5.3-5.6: Seatbelt profile generation tests
# ============================================================================


class TestSeatbeltProfile:
    """Test that _compile_seatbelt_profile correctly uses new config fields."""

    def _make_sandbox(self, **kwargs) -> MacOSSandbox:
        defaults = {
            "mode": SandboxMode.SEATBELT,
            "workspace_dir": "/tmp/test_ws",
            "mounts": [MountSpec(path="/tmp/test_ws", writable=True)],
        }
        defaults.update(kwargs)
        config = SandboxConfig(**defaults)
        return MacOSSandbox(config)

    def test_deny_paths_in_seatbelt_profile(self):
        sandbox = self._make_sandbox(
            deny_paths=["/Users/test/.ssh", "/Users/test/.gnupg"],
        )
        profile = sandbox._compile_seatbelt_profile()

        assert "(deny file-read*" in profile
        assert '(subpath "/Users/test/.ssh")' in profile
        assert '(subpath "/Users/test/.gnupg")' in profile
        # deny_paths should also block writes
        assert "(deny file-write*" in profile

    def test_allow_read_all_true(self):
        sandbox = self._make_sandbox(allow_read_all=True)
        profile = sandbox._compile_seatbelt_profile()

        assert "(allow file-read*)" in profile

    def test_allow_read_all_false(self):
        sandbox = self._make_sandbox(
            allow_read_all=False,
            mounts=[
                MountSpec(path="/tmp/test_ws", writable=True),
                MountSpec(path="/opt/data", writable=False),
            ],
        )
        profile = sandbox._compile_seatbelt_profile()

        # Should NOT have blanket allow file-read*
        # But should have per-mount allow file-read*
        lines = profile.split("\n")
        # Find the "File read" section
        file_read_section = False
        blanket_read = False
        mount_reads = []
        for line in lines:
            if "; File read" in line:
                file_read_section = True
                continue
            if file_read_section:
                if line.strip() == "(allow file-read*)":
                    blanket_read = True
                if "(subpath" in line and "file-read" not in line:
                    # This is a subpath under a previous allow
                    mount_reads.append(line.strip())
                if line.startswith(";") and "File write" in line:
                    break

        assert (
            not blanket_read
        ), "allow_read_all=False should not have blanket (allow file-read*)"
        assert '(subpath "/tmp/test_ws")' in profile
        assert '(subpath "/opt/data")' in profile

    def test_executable_false_generates_deny_exec(self):
        sandbox = self._make_sandbox(
            mounts=[
                MountSpec(path="/tmp/test_ws", writable=True, executable=True),
                MountSpec(
                    path="/tmp/untrusted",
                    writable=True,
                    executable=False,
                ),
            ],
        )
        profile = sandbox._compile_seatbelt_profile()

        assert "(deny process-exec*" in profile
        assert '(subpath "/tmp/untrusted")' in profile
        # Should NOT deny exec for /tmp/test_ws
        # Check that deny process-exec is paired with /tmp/untrusted
        # not /tmp/test_ws
        deny_exec_idx = profile.find("(deny process-exec*")
        assert deny_exec_idx > 0
        after_deny = profile[deny_exec_idx:]
        assert "/tmp/untrusted" in after_deny

    def test_platform_hints_seatbelt_extra_rules(self):
        extra = (
            "(allow iokit-open "
            '(iokit-user-client-class "AGXDeviceUserClient"))'
        )
        sandbox = self._make_sandbox(
            platform_hints={"seatbelt_extra_rules": extra},
        )
        profile = sandbox._compile_seatbelt_profile()

        assert extra in profile
        assert "; Platform hints: extra rules" in profile

    def test_no_platform_hints_no_extra_section(self):
        sandbox = self._make_sandbox()
        profile = sandbox._compile_seatbelt_profile()

        assert "; Platform hints: extra rules" not in profile


# ============================================================================
# Task 5.7: Unsupported features logging
# ============================================================================


class TestUnsupportedFeaturesLogging:
    """Verify macOS logs warnings for unsupported features."""

    def test_max_processes_warning(self):
        sandbox = MacOSSandbox(
            SandboxConfig(
                mode=SandboxMode.SEATBELT,
                workspace_dir="/tmp/ws",
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
                max_processes=10,
            ),
        )
        with patch("qwenpaw.sandbox.macos_sandbox.logger") as mock_logger:
            sandbox._compile_seatbelt_profile()

        assert mock_logger.warning.called
        calls_str = str(mock_logger.warning.call_args_list)
        assert "max_processes" in calls_str
        assert "not supported by Seatbelt" in calls_str

    def test_max_memory_warning(self):
        sandbox = MacOSSandbox(
            SandboxConfig(
                mode=SandboxMode.SEATBELT,
                workspace_dir="/tmp/ws",
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
                max_memory_mb=512,
            ),
        )
        with patch("qwenpaw.sandbox.macos_sandbox.logger") as mock_logger:
            sandbox._compile_seatbelt_profile()

        assert mock_logger.warning.called
        calls_str = str(mock_logger.warning.call_args_list)
        assert "max_memory_mb" in calls_str
        assert "not supported by Seatbelt" in calls_str

    def test_network_ports_warning(self):
        sandbox = MacOSSandbox(
            SandboxConfig(
                mode=SandboxMode.SEATBELT,
                workspace_dir="/tmp/ws",
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
                network_ports=[PortRule(port=443)],
            ),
        )
        with patch("qwenpaw.sandbox.macos_sandbox.logger") as mock_logger:
            sandbox._compile_seatbelt_profile()

        assert mock_logger.warning.called
        calls_str = str(mock_logger.warning.call_args_list)
        assert "network_ports" in calls_str
        assert "not supported by Seatbelt" in calls_str

    def test_no_warning_when_features_not_set(self):
        sandbox = MacOSSandbox(
            SandboxConfig(
                mode=SandboxMode.SEATBELT,
                workspace_dir="/tmp/ws",
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
            ),
        )
        with patch("qwenpaw.sandbox.macos_sandbox.logger") as mock_logger:
            sandbox._compile_seatbelt_profile()

        mock_logger.warning.assert_not_called()
