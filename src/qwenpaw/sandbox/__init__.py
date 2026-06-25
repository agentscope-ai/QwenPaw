# -*- coding: utf-8 -*-
"""Sandbox — lightweight local execution isolation.

Supported modes:
  - SEATBELT:    macOS sandbox-exec kernel isolation
  - BUBBLEWRAP:  Linux bubblewrap mount-namespace isolation (preferred)
  - LANDLOCK:    Linux Landlock LSM kernel isolation (5.13+, fallback)
  - WSL2:        Windows WSL2 delegated execution + Landlock isolation
  - NONE:        no isolation, direct execution

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
    create_sandbox,
    detect_platform_mode,
    probe_sandbox_support,
)
from .bubblewrap_sandbox import BubblewrapSandbox
from .local_sandbox import (
    LocalSandbox,
    NoneSandbox,
)
from .macos_sandbox import MacOSSandbox
from .windows_sandbox import WindowsSandbox

__all__ = [
    "BubblewrapSandbox",
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
