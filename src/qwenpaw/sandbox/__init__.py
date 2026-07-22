# -*- coding: utf-8 -*-
"""Sandbox — lightweight local execution isolation.

Supported modes:
  - SEATBELT:      macOS sandbox-exec kernel isolation.
  - BUBBLEWRAP:    Linux bubblewrap mount-namespace isolation (preferred).
  - LANDLOCK:      Linux Landlock LSM kernel isolation (5.13+, fallback).
  - WINDOWS:       Windows native isolation (Windows 10+). Dispatches on
    ``allow_read_all`` and admin privilege:

    - ``allow_read_all=False`` →
      ``WindowsAppContainerSandbox`` (AppContainer).
    - ``allow_read_all=True`` + admin →
      ``WindowsElevatedSandbox`` (WRITE_RESTRICTED + dedicated user).
    - ``allow_read_all=True`` + no admin →
      ``WindowsUnelevatedSandbox`` (WRITE_RESTRICTED, no admin).
  - NONE:          no isolation, direct execution.

Lifecycle: per-tool-call (created and destroyed for each invocation).

Example:
    ::

        from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode

        config = SandboxConfig(
            mode=SandboxMode.SEATBELT,
            workspace_dir="/path/to/project",
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
from .windows_appcontainer_sandbox import WindowsAppContainerSandbox
from .windows_appcontainer_sandbox import (
    shutdown_cleanup as _appcontainer_shutdown_cleanup,
)
from .windows_elevated_sandbox import (
    WindowsElevatedSandbox,
)
from .windows_elevated_sandbox import (
    shutdown_cleanup as _restricted_shutdown_cleanup,
)
from .windows_unelevated_sandbox import (
    WindowsSandboxBase,
    WindowsUnelevatedSandbox,
)
from .windows_unelevated_sandbox import (
    shutdown_cleanup as _unelevated_shutdown_cleanup,
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
    "WindowsElevatedSandbox",
    "WindowsAppContainerSandbox",
    "WindowsSandboxBase",
    "WindowsUnelevatedSandbox",
    "create_sandbox",
    "detect_platform_mode",
    "probe_sandbox_support",
    "shutdown_all_sandboxes",
]


def shutdown_all_sandboxes() -> None:
    """Destroys all Windows sandbox artifacts on application exit.

    Calls cleanup for all three Windows sandbox backends. Safe to call
    on non-Windows platforms (no-op) and safe to call multiple times.
    """
    import sys

    if sys.platform == "win32":
        _restricted_shutdown_cleanup()
        _appcontainer_shutdown_cleanup()
        _unelevated_shutdown_cleanup()
