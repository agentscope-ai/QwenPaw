# -*- coding: utf-8 -*-
"""Integration tests for the sandbox module (config, probing, factory).

These tests import qwenpaw.sandbox directly and verify configuration
data classes, platform probing, and factory dispatch logic. No HTTP
server needed — these are pure module-level integration tests that
verify the sandbox subsystem's public API contract.
"""

from __future__ import annotations

import sys

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_sandbox_mode_enum_values() -> None:
    """Test purpose:
    - Verify SandboxMode enum has all expected values. Other modules
      depend on these exact string values for configuration.

    Test flow:
    1. Import SandboxMode.
    2. Verify all 5 modes exist with correct string values.
    """
    from qwenpaw.sandbox import SandboxMode

    assert SandboxMode.SEATBELT.value == "seatbelt"
    assert SandboxMode.BUBBLEWRAP.value == "bubblewrap"
    assert SandboxMode.LANDLOCK.value == "landlock"
    assert SandboxMode.WINDOWS.value == "windows"
    assert SandboxMode.NONE.value == "none"


@pytest.mark.integration
@pytest.mark.p1
def test_sandbox_config_dataclass_creation() -> None:
    """Test purpose:
    - Verify SandboxConfig can be created with minimal required fields.
      The factory and all backends depend on this dataclass.

    Test flow:
    1. Create SandboxConfig with mode=NONE and a workspace dir.
    2. Verify defaults are applied correctly.
    """
    from qwenpaw.sandbox.config import SandboxConfig, SandboxMode

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp/test",
    )
    assert config.mode == SandboxMode.NONE
    assert config.workspace_dir == "/tmp/test"
    assert config.allow_read_all is True
    assert config.timeout_seconds == 30
    assert config.mounts == []
    assert config.deny_paths == []
    assert config.network_allow == []


@pytest.mark.integration
@pytest.mark.p1
def test_mount_spec_dataclass() -> None:
    """Test purpose:
    - Verify MountSpec data class has correct defaults.

    Test flow:
    1. Create MountSpec with just a path.
    2. Verify defaults (writable=False, executable=True).
    """
    from qwenpaw.sandbox.config import MountSpec

    mount = MountSpec(path="/some/path")
    assert mount.path == "/some/path"
    assert mount.writable is False
    assert mount.executable is True


@pytest.mark.integration
@pytest.mark.p1
def test_port_rule_dataclass() -> None:
    """Test purpose:
    - Verify PortRule data class has correct defaults.

    Test flow:
    1. Create PortRule with just a port.
    2. Verify defaults (direction=connect, allow=True).
    """
    from qwenpaw.sandbox.config import PortRule

    rule = PortRule(port=8080)
    assert rule.port == 8080
    assert rule.direction == "connect"
    assert rule.allow is True


@pytest.mark.integration
@pytest.mark.p1
def test_execution_result_dataclass() -> None:
    """Test purpose:
    - Verify ExecutionResult data class structure.

    Test flow:
    1. Create ExecutionResult with required fields.
    2. Verify optional fields have correct defaults.
    """
    from qwenpaw.sandbox.config import ExecutionResult

    result = ExecutionResult(
        exit_code=0,
        stdout="hello",
        stderr="",
    )
    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.duration_ms == 0
    assert result.sandbox_violation is None


@pytest.mark.integration
@pytest.mark.p1
def test_probe_sandbox_support_returns_capability() -> None:
    """Test purpose:
    - Verify probe_sandbox_support returns a SandboxCapability on the
      current platform. This is called at startup to determine available
      isolation.

    Test flow:
    1. Call probe_sandbox_support().
    2. Verify result has supported (bool), mode (SandboxMode), reason (str).
    """
    from qwenpaw.sandbox.config import (
        SandboxCapability,
        SandboxMode,
        probe_sandbox_support,
    )

    cap = probe_sandbox_support()
    assert isinstance(cap, SandboxCapability)
    assert isinstance(cap.supported, bool)
    assert isinstance(cap.mode, SandboxMode)
    assert isinstance(cap.reason, str) and cap.reason


@pytest.mark.integration
@pytest.mark.p1
def test_detect_platform_mode_returns_valid_mode() -> None:
    """Test purpose:
    - Verify detect_platform_mode returns a valid SandboxMode for the
      current platform.

    Test flow:
    1. Call detect_platform_mode().
    2. Verify result is a SandboxMode enum value.
    """
    from qwenpaw.sandbox.config import SandboxMode, detect_platform_mode

    mode = detect_platform_mode()
    assert isinstance(mode, SandboxMode)


@pytest.mark.integration
@pytest.mark.p1
def test_create_sandbox_none_mode() -> None:
    """Test purpose:
    - Verify create_sandbox with NONE mode returns a NoneSandbox
      instance. This is the fallback when no isolation is available.

    Test flow:
    1. Create SandboxConfig with mode=NONE.
    2. Call create_sandbox.
    3. Verify returned instance has execute method.
    """
    from qwenpaw.sandbox.config import SandboxConfig
    from qwenpaw.sandbox.config import SandboxMode, create_sandbox

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp",
    )
    sandbox = create_sandbox(config)
    assert sandbox is not None
    assert hasattr(sandbox, "execute")


@pytest.mark.integration
@pytest.mark.p1
def test_create_sandbox_platform_compatibility_guard() -> None:
    """Test purpose:
    - Verify create_sandbox downgrades incompatible modes to platform
      default. E.g., SEATBELT on Linux should fall back to platform
      default, not crash.

    Test flow:
    1. On Linux, create config with mode=SEATBELT.
    2. Call create_sandbox — should not raise, should fall back.
    """
    from qwenpaw.sandbox.config import SandboxConfig
    from qwenpaw.sandbox.config import SandboxMode, create_sandbox

    if sys.platform != "linux":
        pytest.skip("Platform compatibility guard test for Linux")

    config = SandboxConfig(
        mode=SandboxMode.SEATBELT,  # macOS only
        workspace_dir="/tmp",
    )
    # Should not raise — falls back to platform default
    sandbox = create_sandbox(config)
    assert sandbox is not None


@pytest.mark.integration
@pytest.mark.p1
def test_network_allow_is_absolute_block_all() -> None:
    """Test purpose:
    - Verify network_allow_is_absolute returns True for empty list
      (block all) and ["*"] (allow all).

    Test flow:
    1. Create configs with network_allow=[] and network_allow=["*"].
    2. Verify both return True.
    """
    from qwenpaw.sandbox.config import (
        SandboxConfig,
        SandboxMode,
        network_allow_is_absolute,
    )

    config_block = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp",
        network_allow=[],
    )
    assert network_allow_is_absolute(config_block) is True

    config_allow = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp",
        network_allow=["*"],
    )
    assert network_allow_is_absolute(config_allow) is True


@pytest.mark.integration
@pytest.mark.p1
def test_network_allow_is_absolute_domain_list() -> None:
    """Test purpose:
    - Verify network_allow_is_absolute returns False for a domain list
      (partial filtering, not absolute).

    Test flow:
    1. Create config with network_allow=["example.com"].
    2. Verify returns False.
    """
    from qwenpaw.sandbox.config import (
        SandboxConfig,
        SandboxMode,
        network_allow_is_absolute,
    )

    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir="/tmp",
        network_allow=["example.com"],
    )
    assert network_allow_is_absolute(config) is False


@pytest.mark.integration
@pytest.mark.p1
def test_sandbox_capability_landlock_version() -> None:
    """Test purpose:
    - Verify SandboxCapability has landlock_abi_version field with
      default 0. Linux-only field but dataclass exists on all platforms.

    Test flow:
    1. Create SandboxCapability with minimal fields.
    2. Verify landlock_abi_version defaults to 0.
    """
    from qwenpaw.sandbox.config import SandboxCapability, SandboxMode

    cap = SandboxCapability(
        supported=False,
        mode=SandboxMode.NONE,
        reason="test",
    )
    assert cap.landlock_abi_version == 0


@pytest.mark.integration
@pytest.mark.p1
def test_none_sandbox_execute_command() -> None:
    """Test purpose:
    - Verify NoneSandbox can execute a simple command. This is the
      baseline sandbox (no isolation) used when no backend is available.

    Test flow:
    1. Create NoneSandbox with a config.
    2. Execute "echo hello" and verify output.
    """
    import asyncio
    import tempfile

    from qwenpaw.sandbox.config import SandboxConfig, SandboxMode
    from qwenpaw.sandbox.local_sandbox import NoneSandbox

    with tempfile.TemporaryDirectory() as tmpdir:
        config = SandboxConfig(
            mode=SandboxMode.NONE,
            workspace_dir=tmpdir,
        )
        sandbox = NoneSandbox(config)

        async def _run():
            async with sandbox:
                return await sandbox.execute("echo hello")

        result = asyncio.run(_run())
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        assert "hello" in result.stdout
