# -*- coding: utf-8 -*-
"""Sandbox configuration and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SandboxMode(str, Enum):
    """Sandbox isolation modes."""

    SEATBELT = "seatbelt"  # macOS sandbox-exec
    LANDLOCK = "landlock"  # Linux (future)
    WSL2 = "wsl2"  # Windows (future)
    NONE = "none"  # no isolation, direct execution


@dataclass
class MountSpec:
    """A single path-permission declaration.

    Attributes:
        path: Filesystem path.
        writable: True = read/write, False = read-only.
        executable: True = binaries inside the path may be exec'd,
            False = execution is forbidden.
    """

    path: str
    writable: bool = False
    executable: bool = True


@dataclass
class PortRule:
    """TCP port rule.

    Attributes:
        port: TCP port number.
        direction: "connect" (outbound connect) or "bind" (listen).
        allow: True = allow, False = deny.
    """

    port: int
    direction: str = "connect"  # "connect" | "bind"
    allow: bool = True


@dataclass
class SandboxConfig:
    """Full sandbox constraint configuration.

    Allow-list model: anything not explicitly listed is denied.
    """

    mode: SandboxMode
    workspace_dir: str
    mounts: List[MountSpec] = field(default_factory=list)

    # --- Read control ---
    allow_read_all: bool = True
    """True  = all files readable by default (deny-list mode).
    False = only paths declared in ``mounts`` are readable (allow-list mode).
    """

    deny_paths: List[str] = field(default_factory=list)
    """Sensitive paths explicitly denied for read/write.

    Takes precedence over ``allow_read_all`` and ``mounts``.
    """

    # --- Network ---
    network_allow: List[str] = field(default_factory=list)
    """Domain allow-list. ``["*"]`` = open, ``[]`` = closed.

    Domain-level filtering is best-effort and requires proxy-layer support.
    """

    network_ports: Optional[List[PortRule]] = None
    """TCP port-level control.

    Natively supported by Linux Landlock v4; on other platforms degrades to
    fully-open / fully-closed.
    """

    # --- Resource limits ---
    max_processes: Optional[int] = None
    """Maximum child-process count.

    Native on Windows Job objects and Linux cgroups; ignored on macOS.
    """

    max_memory_mb: Optional[int] = None
    """Maximum memory (MB).

    Native on Windows Job objects and Linux cgroups; ignored on macOS.
    """

    # --- Execution control ---
    timeout_seconds: int = 30
    env_vars: Dict[str, str] = field(default_factory=dict)
    """Environment variable override map.

    Unified semantics across all backends:
        - ``value != ""`` → set ``key=value`` in the child process environment.
        - ``value == ""`` → treated as **unset**, ``pop(key)`` from the child
          environment.  This is required so the governor can use
          ``env_vars={k: ""}`` as a sensitive-variable blocklist: some
          libraries probe ``key in os.environ`` for presence, and merely
          blanking the value would still leave the key visible.
    """

    env_mode: str = "inject"
    """'inject' = append to the current environment;
    'allowlist' = pass through only the variables explicitly declared.

    .. warning:: ``allowlist`` mode is currently **not implemented**.  All
        backends behave as ``inject`` regardless of this field.

    .. todo:: Either implement ``allowlist`` or drop this field entirely.
        Implementation notes if kept:
        - the local / linux / windows backends should clear the inherited
          environment in ``allowlist`` mode and inject only the variables
          declared in ``env_vars``;
        - retain the minimum set of variables the sandbox itself needs
          (``PATH``, ``HOME``, ``LANG``); otherwise most child commands
          will fail.
    """

    # --- Platform passthrough (escape hatch) ---
    platform_hints: Dict[str, Any] = field(default_factory=dict)
    """Rarely used. Forwards platform-native parameters such as
    ``seatbelt_extra_rules`` / ``landlock_extra_flags``.
    """


@dataclass
class ExecutionResult:
    """Return value of ``sandbox.execute()``."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: int = 0
    sandbox_violation: Optional[str] = None


@dataclass
class SandboxCapability:
    """Result of probing platform sandbox support.

    Obtained at startup via :func:`probe_sandbox_support`.
    """

    supported: bool
    mode: SandboxMode
    reason: str  # human-readable reason
    landlock_abi_version: int = 0
    """Linux only: detected Landlock ABI version (0 = unsupported)."""


def _probe_linux_landlock() -> SandboxCapability:
    """Probe Linux Landlock support.

    Steps:
        1. Kernel version >= 5.13.
        2. ``/sys/kernel/security/lsm`` contains ``"landlock"``.
        3. ``landlock_create_ruleset`` syscall returns the ABI version.
    """
    import os
    import struct
    import ctypes
    import ctypes.util

    # Step 1: check kernel version
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

    # Step 2: check the LSM list
    try:
        with open("/sys/kernel/security/lsm", "r") as f:
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

    # Step 3: probe ABI version via landlock_create_ruleset(NULL, 0,
    # LANDLOCK_CREATE_RULESET_VERSION)
    try:
        libc = ctypes.CDLL(
            ctypes.util.find_library("c") or "libc.so.6", use_errno=True
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
                reason=f"Kernel {major}.{minor}, Landlock in LSM (ABI version unknown, arch={arch})",
                landlock_abi_version=1,
            )

        LANDLOCK_CREATE_RULESET_VERSION = 1 << 0  # flags bit

        # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION) returns ABI version
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
                reason=f"landlock_create_ruleset syscall failed, errno={errno}",
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
    """Probe macOS Seatbelt support."""
    import shutil

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


def _probe_windows_wsl2() -> SandboxCapability:
    """Probe Windows WSL2 + Landlock support.

    Steps:
        1. ``wsl.exe`` is available.
        2. At least one WSL2 distribution is installed.
        3. ``python3`` exists inside the WSL2 distribution.
        4. The WSL2 distribution kernel supports Landlock.
    """
    try:
        from .windows_sandbox import (
            check_wsl_landlock,
            check_wsl_python3,
            probe_wsl2_availability,
        )
    except ImportError as e:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Failed to import windows_sandbox module: {e}",
        )

    available, distro, reason = probe_wsl2_availability()
    if not available:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"WSL2 unavailable: {reason}",
        )

    if not check_wsl_python3(distro):
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"python3 not found in WSL2 distro '{distro}'",
        )

    supported, abi_version = check_wsl_landlock(distro)
    if not supported:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Landlock not supported in WSL2 distro '{distro}' kernel",
        )

    return SandboxCapability(
        supported=True,
        mode=SandboxMode.WSL2,
        reason=f"WSL2 distro '{distro}' with Landlock ABI v{abi_version}",
        landlock_abi_version=abi_version,
    )


def probe_sandbox_support() -> SandboxCapability:
    """Probe the current platform's sandbox support at startup.

    Returns a :class:`SandboxCapability` describing whether sandbox isolation
    is available.  When unsupported, ``mode`` is :attr:`SandboxMode.NONE` and
    callers should refuse to take the SANDBOX_FALLBACK code path.
    """
    import sys

    if sys.platform == "darwin":
        return _probe_macos_seatbelt()
    elif sys.platform == "linux":
        return _probe_linux_landlock()
    elif sys.platform == "win32":
        # Windows sandbox (WSL2 + Landlock) is currently disabled because the
        # WSL2 delegation path is not production-ready. Re-enable by calling
        # ``_probe_windows_wsl2()`` once the Windows sandbox path is ready.
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason="Windows sandbox temporarily disabled until WSL2 path is ready",
        )
    else:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Unsupported platform: {sys.platform}",
        )


def detect_platform_mode() -> SandboxMode:
    """Pick the sandbox mode based on the current OS.

    Calls :func:`probe_sandbox_support` for a real capability probe; returns
    :attr:`SandboxMode.NONE` if the platform does not support sandbox
    isolation.
    """
    cap = probe_sandbox_support()
    return cap.mode
