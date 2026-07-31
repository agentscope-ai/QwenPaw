# -*- coding: utf-8 -*-
"""Sandbox configuration, capability probing, and factory.

This is the entry point of the :mod:`qwenpaw.sandbox` package: it defines
the constraint vocabulary (modes, mounts, ports), probes platform sandbox
support, and provides the factory that maps a ``SandboxConfig`` to a
concrete backend.

Backend dispatch (via ``create_sandbox``):
    SEATBELT:
        ``MacOSSandbox`` — macOS sandbox-exec.
    BUBBLEWRAP:
        ``BubblewrapSandbox`` — Linux bubblewrap (preferred).
    LANDLOCK:
        ``LinuxSandbox`` — Linux Landlock LSM (fallback).
    WINDOWS:
        Dispatches on ``allow_read_all`` and admin privilege:

        - ``allow_read_all=False`` →
          ``WindowsAppContainerSandbox`` (AppContainer).
        - ``allow_read_all=True`` + admin →
          ``WindowsElevatedSandbox`` (WRITE_RESTRICTED + dedicated user).
        - ``allow_read_all=True`` + no admin →
          ``WindowsUnelevatedSandbox`` (WRITE_RESTRICTED, no admin).
    NONE:
        ``NoneSandbox`` — no isolation.

Example:
    ::

        from .sandbox import create_sandbox, SandboxConfig, SandboxMode

        config = SandboxConfig(
            mode=SandboxMode.BUBBLEWRAP,
            workspace_dir="/path/to/project",
        )
        async with create_sandbox(config) as sandbox:
            result = await sandbox.execute("echo hello")
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SandboxMode(str, Enum):
    """Sandbox isolation mode.

    Attributes:
        SEATBELT: macOS sandbox-exec.
        BUBBLEWRAP: Linux bubblewrap (preferred).
        LANDLOCK: Linux Landlock LSM (fallback).
        WINDOWS: Windows native (AppContainer / WRITE_RESTRICTED token).
        NONE: No isolation, direct execution.
    """

    SEATBELT = "seatbelt"  # macOS sandbox-exec
    BUBBLEWRAP = "bubblewrap"  # Linux bubblewrap (preferred)
    LANDLOCK = "landlock"  # Linux Landlock LSM (fallback)
    WINDOWS = "windows"  # Windows (AppContainer / WRITE_RESTRICTED token)
    NONE = "none"  # No isolation, direct execution


@dataclass
class MountSpec:
    """A single path permission declaration.

    Attributes:
        path: Filesystem path.
        writable: True = read-write, False = read-only.
        executable: True = allow executing binaries under this path.
    """

    path: str
    writable: bool = False
    executable: bool = True


@dataclass
class PortRule:
    """TCP port rule.

    Attributes:
        port: TCP port number.
        direction: "connect" (outbound) or "bind" (listen).
        allow: True = permit, False = deny.
    """

    port: int
    direction: str = "connect"  # "connect" | "bind"
    allow: bool = True


@dataclass
class SandboxConfig:
    """Complete sandbox constraint configuration.

    Uses an allowlist model: unlisted paths and capabilities are denied.

    Attributes:
        mode: Sandbox isolation mode.
        workspace_dir: Root working directory for the sandbox.
        mounts: Additional path permission declarations.
        allow_read_all: If True, allows reading all files by default
            (deny-list mode). If False, only paths in ``mounts`` are
            readable (allow-list mode).
        deny_paths: Sensitive paths explicitly denied regardless of
            other settings.
        network_allow: Domain allowlist. ``["*"]`` opens all network
            access; ``[]`` blocks all. Domain-level filtering is
            best-effort.
        network_ports: TCP port-level control. Native on Linux
            Landlock v4; other platforms degrade to all-open/all-blocked.
        max_processes: Max subprocess count (Windows Job / Linux cgroups).
        max_memory_mb: Max memory in MB (Windows Job / Linux cgroups).
        timeout_seconds: Command execution timeout.
        env_vars: Additional environment variables.
        env_mode: ``"inject"`` appends to current environment;
            ``"allowlist"`` passes only declared variables.
        shell_executable: Shell for command execution. When None, the
            platform backend chooses its default.
        platform_hints: Pass-through for platform-native parameters.
    """

    mode: SandboxMode
    workspace_dir: str
    mounts: List[MountSpec] = field(default_factory=list)

    allow_read_all: bool = True
    deny_paths: List[str] = field(default_factory=list)

    network_allow: List[str] = field(default_factory=list)
    network_ports: Optional[List[PortRule]] = None

    max_processes: Optional[int] = None
    max_memory_mb: Optional[int] = None

    timeout_seconds: int = 30
    env_vars: Dict[str, str] = field(default_factory=dict)
    env_mode: str = "inject"
    shell_executable: Optional[str] = None
    platform_hints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result of a sandbox command execution.

    Attributes:
        exit_code: Process exit code.
        stdout: Captured standard output.
        stderr: Captured standard error.
        timed_out: Whether the command was killed due to timeout.
        duration_ms: Wall-clock execution time in milliseconds.
        sandbox_violation: Violation message if access was denied,
            None otherwise.
    """

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: int = 0
    sandbox_violation: Optional[str] = None


@dataclass
class SandboxCapability:
    """Platform sandbox capability probe result.

    Obtained via ``probe_sandbox_support()`` at startup.

    Attributes:
        supported: Whether sandbox isolation is available.
        mode: Detected sandbox mode (``NONE`` if unsupported).
        reason: Human-readable explanation.
        landlock_abi_version: Linux Landlock ABI version
            (0 = unsupported).
    """

    supported: bool
    mode: SandboxMode
    reason: str  # Human-readable reason
    landlock_abi_version: int = (
        0  # Linux only: Landlock ABI version (0=unsupported)
    )


def _probe_linux_landlock() -> (  # pylint: disable=too-many-return-statements
    SandboxCapability
):
    """Probes Linux Landlock support.

    Detection steps:
        1. Kernel version >= 5.13.
        2. ``/sys/kernel/security/lsm`` contains ``"landlock"``.
        3. ``landlock_create_ruleset`` syscall returns ABI version.

    Returns:
        Probe result with ``mode=LANDLOCK`` on success.
    """
    import ctypes
    import ctypes.util
    import os

    # Step 1: Check kernel version
    try:
        release = os.uname().release  # e.g. "5.15.0-125-generic"
        parts = release.split(".", 2)
        major, minor = int(parts[0]), int(parts[1])
    except (AttributeError, ValueError, IndexError):
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Cannot parse kernel version",
        )

    if (major, minor) < (5, 13):
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Kernel {major}.{minor} < 5.13, Landlock unavailable",
        )

    # Step 2: Check LSM list
    try:
        with open("/sys/kernel/security/lsm", "r", encoding="utf-8") as f:
            lsm_list = f.read().strip()
        if "landlock" not in lsm_list:
            return SandboxCapability(
                supported=False,
                mode=SandboxMode.NONE,
                reason=f"Landlock not in LSM list: {lsm_list}",
            )
    except OSError:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Cannot read /sys/kernel/security/lsm",
        )

    # Step 3: Probe ABI version via landlock_create_ruleset(
    #     NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
    try:
        libc = ctypes.CDLL(
            ctypes.util.find_library("c") or "libc.so.6",
            use_errno=True,
        )
        # syscall numbers for x86_64
        import platform

        arch = platform.machine()
        if arch == "x86_64":
            SYS_landlock_create_ruleset = 444
        elif arch == "aarch64":
            SYS_landlock_create_ruleset = 444
        else:
            # Fallback: assume support based on kernel + LSM check
            return SandboxCapability(
                supported=True,
                mode=SandboxMode.LANDLOCK,
                reason=(
                    f"Kernel {major}.{minor}, Landlock in LSM "
                    f"(ABI version unknown, arch={arch})"
                ),
                landlock_abi_version=1,
            )

        LANDLOCK_CREATE_RULESET_VERSION = 1 << 0  # flags bit

        # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
        # returns ABI version
        libc.syscall.restype = ctypes.c_long
        libc.syscall.argtypes = [
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
        ]
        abi_version = libc.syscall(
            SYS_landlock_create_ruleset,
            None,  # attr = NULL
            0,  # size = 0
            LANDLOCK_CREATE_RULESET_VERSION,
        )

        if abi_version < 0:
            errno = ctypes.get_errno()
            return SandboxCapability(
                supported=False,
                mode=SandboxMode.NONE,
                reason=(
                    f"landlock_create_ruleset syscall failed, errno={errno}"
                ),
            )

        return SandboxCapability(
            supported=True,
            mode=SandboxMode.LANDLOCK,
            reason=f"Kernel {major}.{minor}, Landlock ABI v{abi_version}",
            landlock_abi_version=int(abi_version),
        )
    except (OSError, AttributeError) as e:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Landlock syscall probe failed: {e}",
        )


def _probe_macos_seatbelt() -> SandboxCapability:
    """Probes macOS Seatbelt (sandbox-exec) support.

    Returns:
        Probe result with ``mode=SEATBELT`` if ``sandbox-exec`` is found.
    """
    if shutil.which("sandbox-exec"):
        return SandboxCapability(
            supported=True,
            mode=SandboxMode.SEATBELT,
            reason="sandbox-exec available",
        )
    return SandboxCapability(
        supported=False,
        mode=SandboxMode.NONE,
        reason="sandbox-exec not found",
    )


def _probe_windows() -> SandboxCapability:
    """Probes Windows sandbox support.

    Detection steps:
        1. ``sys.platform == "win32"``
        2. Windows 10+ (build 10240+).
        3. ``CreateRestrictedToken`` API is callable (advapi32.dll).
        4. Optional: AppContainer API (userenv.dll) + ``icacls.exe``.

    Succeeds if at least the WRITE_RESTRICTED token path is available.

    Returns:
        Probe result with ``mode=WINDOWS`` on success.
    """
    import sys

    if sys.platform != "win32":
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Not running on Windows",
        )

    try:
        ver = sys.getwindowsversion()
        if ver.major < 10:
            return SandboxCapability(
                supported=False,
                mode=SandboxMode.NONE,
                reason=(
                    f"Windows {ver.major}.{ver.minor} < 10.0; "
                    f"sandbox requires Windows 10+"
                ),
            )
    except AttributeError:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Cannot determine Windows version",
        )

    # CreateRestrictedToken is the minimum requirement (used by both
    # the unelevated and elevated backends).
    try:
        import ctypes

        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        _ = advapi32.CreateRestrictedToken
    except (OSError, AttributeError) as e:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"CreateRestrictedToken API not available: {e}",
        )

    # AppContainer is optional (needs icacls + userenv.dll).
    has_appcontainer = False
    if shutil.which("icacls"):
        try:
            userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
            _ = userenv.CreateAppContainerProfile
            has_appcontainer = True
        except (OSError, AttributeError):
            pass

    backends = "WRITE_RESTRICTED token"
    if has_appcontainer:
        backends += " + AppContainer"

    return SandboxCapability(
        supported=True,
        mode=SandboxMode.WINDOWS,
        reason=(
            f"Windows {ver.major}.{ver.minor} build {ver.build}; "
            f"{backends} available"
        ),
    )


def _probe_linux_bubblewrap() -> SandboxCapability:
    """Probes bubblewrap (bwrap) availability on Linux.

    Detection steps:
        1. ``bwrap`` binary exists on ``PATH``.
        2. Test run with ``--unshare-user`` confirms user namespaces work.

    Returns:
        Probe result with ``mode=BUBBLEWRAP`` on success.
    """
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="bwrap not found on PATH",
        )
    # Probe: attempt a trivial sandboxed execution to confirm
    # user namespace and mount namespace work.
    try:
        result = subprocess.run(  # noqa: S603, pylint: disable=W1510
            [
                bwrap,
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--unshare-user",
                "--unshare-pid",
                "--proc",
                "/proc",
                "--",
                "/bin/true",
            ],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return SandboxCapability(
                supported=True,
                mode=SandboxMode.BUBBLEWRAP,
                reason="bubblewrap available with user namespaces",
            )
        stderr = result.stderr.decode("utf-8", errors="replace")
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=(
                f"bwrap probe failed (rc={result.returncode}): {stderr[:200]}"
            ),
        )
    except subprocess.TimeoutExpired:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="bwrap probe timed out",
        )
    except (FileNotFoundError, OSError) as e:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"bwrap probe error: {e}",
        )


@functools.lru_cache(maxsize=1)
def probe_sandbox_support() -> SandboxCapability:
    """Probes current platform sandbox support.

    On Linux the priority is: bubblewrap > Landlock > NONE.

    The result is cached (single invocation per process) because
    OS-level sandbox capability does not change at runtime. The first
    call may block briefly (e.g. a subprocess probe on Linux).

    Returns:
        ``SandboxCapability`` describing available isolation.
    """
    import sys

    if sys.platform == "darwin":
        return _probe_macos_seatbelt()
    elif sys.platform == "linux":
        cap = _probe_linux_bubblewrap()
        if cap.supported:
            return cap
        return _probe_linux_landlock()
    elif sys.platform == "win32":
        return _probe_windows()
    else:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Unsupported platform: {sys.platform}",
        )


def detect_platform_mode() -> SandboxMode:
    """Auto-detects sandbox mode for the current OS.

    Returns:
        Detected ``SandboxMode``, or ``NONE`` if unsupported.
    """
    cap = probe_sandbox_support()
    return cap.mode


# ═══════════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════════


def create_sandbox(  # pylint: disable=too-many-return-statements
    config: SandboxConfig,
) -> Any:
    """Creates a sandbox instance for the given configuration.

    Dispatches to the appropriate backend based on ``config.mode``.
    For Windows mode, further dispatches on ``allow_read_all`` and
    admin privilege.

    Args:
        config: Sandbox configuration.

    Returns:
        A sandbox instance (async context manager with ``execute()``).

    Raises:
        ValueError: If ``config.mode`` is unknown.
    """
    if config.mode == SandboxMode.SEATBELT:
        from .macos_sandbox import MacOSSandbox

        return MacOSSandbox(config)
    elif config.mode == SandboxMode.NONE:
        from .local_sandbox import NoneSandbox

        return NoneSandbox(config)
    elif config.mode == SandboxMode.BUBBLEWRAP:
        from .bubblewrap_sandbox import BubblewrapSandbox

        return BubblewrapSandbox(config)
    elif config.mode == SandboxMode.LANDLOCK:
        from .linux_sandbox import LinuxSandbox

        return LinuxSandbox(config)
    elif config.mode == SandboxMode.WINDOWS:
        if not config.allow_read_all:
            from .windows_appcontainer_sandbox import (
                WindowsAppContainerSandbox,
            )

            return WindowsAppContainerSandbox(config)
        from .windows_unelevated_sandbox import _is_admin

        if _is_admin():
            from .windows_elevated_sandbox import WindowsElevatedSandbox

            return WindowsElevatedSandbox(config)
        from .windows_unelevated_sandbox import WindowsUnelevatedSandbox

        return WindowsUnelevatedSandbox(config)
    else:
        raise ValueError(f"Unknown sandbox mode: {config.mode}")
