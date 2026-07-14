# -*- coding: utf-8 -*-
"""Sandbox — lightweight local execution isolation.

Supported modes:
  - SEATBELT:      macOS sandbox-exec kernel isolation
  - BUBBLEWRAP:    Linux bubblewrap mount-namespace isolation (preferred)
  - LANDLOCK:      Linux Landlock LSM kernel isolation (5.13+, fallback)
  - APPCONTAINER:  Windows native isolation (Windows 10+). Dispatches on
    allow_read_all: True → WindowsRestrictedSandbox (WRITE_RESTRICTED token),
    False → WindowsSandbox (AppContainer).
  - NONE:          no isolation, direct execution

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

from .bubblewrap_sandbox import BubblewrapSandbox
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
from .local_sandbox import (
    LocalSandbox,
    NoneSandbox,
)
from .macos_sandbox import MacOSSandbox
from .windows_restricted_sandbox import (
    WindowsRestrictedSandbox,
)
from .windows_restricted_sandbox import (
    shutdown_cleanup as _restricted_shutdown_cleanup,
)
from .windows_sandbox import WindowsSandbox
from .windows_sandbox import (
    shutdown_cleanup as _appcontainer_shutdown_cleanup,
)

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
    "WindowsRestrictedSandbox",
    "WindowsSandbox",
    "create_sandbox",
    "detect_platform_mode",
    "probe_sandbox_support",
    "shutdown_all_sandboxes",
]


def shutdown_all_sandboxes() -> None:
    """Destroys all Windows sandbox artifacts on application exit.

    Calls both sandbox backend cleanups. Safe to call on non-Windows
    platforms (no-op). Safe to call multiple times.
    """
    import sys

    if sys.platform == "win32":
        _restricted_shutdown_cleanup()
        _appcontainer_shutdown_cleanup()
