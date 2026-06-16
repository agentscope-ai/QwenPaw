# -*- coding: utf-8 -*-
"""Sandbox — lightweight local execution isolation.

Supported modes:
  - SEATBELT: macOS sandbox-exec kernel isolation
  - LANDLOCK: Linux Landlock LSM kernel isolation (5.13+)
  - WSL2:     Windows WSL2 delegated execution + Landlock isolation
  - NONE:     no isolation, direct execution

Lifecycle: per-tool-call (created and destroyed for each invocation).

Usage:
    from qwenpaw.sandbox import (
        create_sandbox, SandboxConfig, SandboxMode, MountSpec,
    )

    config = SandboxConfig(
        mode=SandboxMode.SEATBELT,
        workspace_dir="/path/to/project",
        mounts=[MountSpec(path="/path/to/project", writable=True)],
    )
    async with create_sandbox(config) as sandbox:
        result = await sandbox.execute("echo hello")
        print(result.stdout)
"""

from .config import (
    ExecutionResult,
    MountSpec,
    PortRule,
    SandboxCapability,
    SandboxConfig,
    SandboxMode,
    detect_platform_mode,
    probe_sandbox_support,
)
from .local_sandbox import (
    LocalSandbox,
    MacOSSandbox,
    NoneSandbox,
    create_sandbox,
)
from .windows_sandbox import WindowsSandbox

__all__ = [
    "ExecutionResult",
    "LocalSandbox",
    "MacOSSandbox",
    "MountSpec",
    "NoneSandbox",
    "PortRule",
    "SandboxCapability",
    "SandboxConfig",
    "SandboxMode",
    "WindowsSandbox",
    "create_sandbox",
    "detect_platform_mode",
    "probe_sandbox_support",
]
