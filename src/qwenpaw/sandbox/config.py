# -*- coding: utf-8 -*-
"""Sandbox — configuration, capability probing, and factory (entry point).

This is the natural entry point into the :mod:`qwenpaw.sandbox` package:
it defines the constraint vocabulary (modes, mounts, ports), probes what
the current platform actually supports, and ships the factory that maps a
``SandboxConfig`` to a concrete backend.

Backend layout (``create_sandbox`` dispatches to these by ``SandboxMode``):
  - SEATBELT     → mod:`qwenpaw.sandbox.macos_sandbox`      (MacOSSandbox)
  - BUBBLEWRAP   → mod:`qwenpaw.sandbox.bubblewrap_sandbox` (BubblewrapSandbox)
  - LANDLOCK     → mod:`qwenpaw.sandbox.linux_sandbox`      (LinuxSandbox)
  - APPCONTAINER → mod:`qwenpaw.sandbox.windows_sandbox`    (WindowsSandbox)
  - NONE         → mod:`qwenpaw.sandbox.local_sandbox`      (NoneSandbox)

Shared base class for all backends:
  - :class:`qwenpaw.sandbox.local_sandbox.LocalSandbox`

Typical usage:
    from .sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec
    config = SandboxConfig(
        mode=SandboxMode.BUBBLEWRAP,
        workspace_dir="/path/to/project",
        mounts=[MountSpec(path="/path/to/project", writable=True)],
    )
    async with create_sandbox(config) as sandbox:
        result = await sandbox.execute("echo hello")
        print(result.stdout)
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SandboxMode(str, Enum):
    """Sandbox isolation mode."""

    SEATBELT = "seatbelt"  # macOS sandbox-exec
    BUBBLEWRAP = "bubblewrap"  # Linux bubblewrap (preferred)
    LANDLOCK = "landlock"  # Linux Landlock LSM (fallback)
    APPCONTAINER = "appcontainer"  # Windows AppContainer (native)
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

    Allowlist model: unlisted = deny.
    """

    mode: SandboxMode
    workspace_dir: str
    mounts: List[MountSpec] = field(default_factory=list)

    # --- Read control ---
    allow_read_all: bool = True
    """True = allow reading all files by default (deny-list mode).
    False = only paths declared in mounts are readable (allow-list mode)."""

    deny_paths: List[str] = field(default_factory=list)
    """Sensitive paths explicitly denied for read/write (takes priority over
    allow_read_all and mounts)."""

    # --- Network ---
    network_allow: List[str] = field(default_factory=list)
    """Domain allowlist. ["*"] = all open, [] = all blocked.
    Domain-level filtering is best-effort (requires proxy layer support)."""

    network_ports: Optional[List[PortRule]] = None
    """TCP port-level control (Linux Landlock v4 native; other platforms
    degrade to all-open/all-blocked)."""

    # --- Resource limits ---
    max_processes: Optional[int] = None
    """Max subprocess count. Windows Job native, Linux cgroups,
    macOS unsupported (ignored)."""

    max_memory_mb: Optional[int] = None
    """Max memory (MB). Windows Job native, Linux cgroups,
    macOS unsupported (ignored)."""

    # --- Execution control ---
    timeout_seconds: int = 30
    env_vars: Dict[str, str] = field(default_factory=dict)
    env_mode: str = "inject"
    """'inject' = append to current environment,
    'allowlist' = only pass declared variables."""

    # --- Platform passthrough (escape hatch) ---
    platform_hints: Dict[str, Any] = field(default_factory=dict)
    """Rarely used. Pass-through for platform-native parameters such as
    seatbelt_extra_rules / landlock_extra_flags."""


@dataclass
class ExecutionResult:
    """Return value of sandbox.execute()."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: int = 0
    sandbox_violation: Optional[str] = None


@dataclass
class SandboxCapability:
    """Platform sandbox capability probe result.

    Obtained at startup via probe_sandbox_support().
    """

    supported: bool
    mode: SandboxMode
    reason: str  # Human-readable reason
    landlock_abi_version: int = (
        0  # Linux only: Landlock ABI version (0=unsupported)
    )


def _probe_linux_landlock() -> (
    SandboxCapability
):  # pylint: disable=too-many-return-statements
    """Probe Linux Landlock support.

    Detection steps:
        1. Kernel version >= 5.13
        2. /sys/kernel/security/lsm contains "landlock"
        3. Attempt landlock_create_ruleset syscall to detect ABI version
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
    """Probe macOS Seatbelt (sandbox-exec) support."""
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


def _probe_windows_appcontainer() -> SandboxCapability:
    """Probe Windows AppContainer support.

    Detection steps:
        1. sys.platform == "win32"
        2. Windows 10+ (build 10240+)
        3. icacls.exe is on PATH
        4. CreateAppContainerProfile API is callable (via ctypes)
    """
    import sys

    if sys.platform != "win32":
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Not running on Windows",
        )

    # Check Windows version (need 10+)
    try:
        ver = sys.getwindowsversion()
        if ver.major < 10:
            return SandboxCapability(
                supported=False,
                mode=SandboxMode.NONE,
                reason=(
                    f"Windows {ver.major}.{ver.minor} < 10.0; "
                    f"AppContainer requires Windows 10+"
                ),
            )
    except AttributeError:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Cannot determine Windows version",
        )

    # Check icacls.exe
    if not shutil.which("icacls"):
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="icacls.exe not found on PATH",
        )

    # Check that AppContainer APIs are available (userenv.dll)
    try:
        import ctypes

        userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        # Verify the function pointer exists
        _ = userenv.CreateAppContainerProfile
    except (OSError, AttributeError) as e:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"AppContainer API not available: {e}",
        )

    return SandboxCapability(
        supported=True,
        mode=SandboxMode.APPCONTAINER,
        reason=(
            f"Windows {ver.major}.{ver.minor} build {ver.build}; "
            f"AppContainer available"
        ),
    )


def _probe_linux_bubblewrap() -> SandboxCapability:
    """Probe bubblewrap (bwrap) availability on Linux.

    Detection steps:
        1. bwrap binary exists on PATH
        2. User namespaces work (test run with --unshare-user)
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


def probe_sandbox_support() -> SandboxCapability:
    """Probe current platform sandbox support at startup.

    Returns a SandboxCapability describing whether sandbox isolation is
    available. If unsupported, mode is NONE and callers should block
    the SANDBOX_FALLBACK path.

    On Linux the priority is: bubblewrap > Landlock > NONE.
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
        return _probe_windows_appcontainer()
    else:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Unsupported platform: {sys.platform}",
        )


def detect_platform_mode() -> SandboxMode:
    """Auto-detect sandbox mode based on current OS.

    Calls probe_sandbox_support() for real capability probing.
    Returns NONE if the platform does not support sandbox isolation.
    """
    cap = probe_sandbox_support()
    return cap.mode


# ═══════════════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════════════


def create_sandbox(config: SandboxConfig) -> Any:
    """Create a sandbox instance based on ``config.mode``.

    Supported modes:
      - SEATBELT      → MacOSSandbox
      - BUBBLEWRAP    → BubblewrapSandbox (Linux preferred)
      - LANDLOCK      → LinuxSandbox (Linux fallback)
      - APPCONTAINER  → WindowsSandbox (Windows 10+ native)
      - NONE          → NoneSandbox
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
    elif config.mode == SandboxMode.APPCONTAINER:
        from .windows_sandbox import WindowsSandbox

        return WindowsSandbox(config)
    else:
        raise ValueError(f"Unknown sandbox mode: {config.mode}")
