# -*- coding: utf-8 -*-
"""Sandbox — 轻量级本地执行隔离。

支持模式：
  - SEATBELT: macOS sandbox-exec 内核隔离
  - LANDLOCK: Linux Landlock LSM 内核隔离 (5.13+)
  - WSL2: Windows WSL2 委托执行 + Landlock 隔离
  - NONE: 不隔离，直接执行

生命周期：per-tool-call（用完即销毁）。

Usage:
    from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec

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
