# -*- coding: utf-8 -*-
"""Sandbox configuration and result types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SandboxMode(str, Enum):
    """沙箱隔离模式。"""

    SEATBELT = "seatbelt"  # macOS sandbox-exec
    LANDLOCK = "landlock"  # Linux (future)
    WSL2 = "wsl2"          # Windows (future)
    NONE = "none"          # 不隔离，直接执行


@dataclass
class MountSpec:
    """一条路径权限声明。

    Attributes:
        path: 路径。
        writable: True 表示可读写，False 表示只读。
        executable: True 表示允许执行该路径下的二进制，False 则禁止。
    """

    path: str
    writable: bool = False
    executable: bool = True


@dataclass
class PortRule:
    """TCP 端口规则。

    Attributes:
        port: TCP 端口号。
        direction: "connect"（出站连接）或 "bind"（绑定监听）。
        allow: True 表示允许，False 表示拒绝。
    """

    port: int
    direction: str = "connect"  # "connect" | "bind"
    allow: bool = True


@dataclass
class SandboxConfig:
    """sandbox 的完整约束配置。白名单模型：未列入 = 拒绝。"""

    mode: SandboxMode
    workspace_dir: str
    mounts: List[MountSpec] = field(default_factory=list)

    # --- 读控制 ---
    allow_read_all: bool = True
    """True = 默认可读所有文件（deny-list 模式）。
    False = 只能读 mounts 声明的路径（allow-list 模式）。"""

    deny_paths: List[str] = field(default_factory=list)
    """显式拒绝读写的敏感路径列表（优先级高于 allow_read_all 和 mounts）。"""

    # --- 网络 ---
    network_allow: List[str] = field(default_factory=list)
    """域名白名单。["*"]=全开, []=全关。域名级过滤为 best-effort（需代理层支持）。"""

    network_ports: Optional[List[PortRule]] = None
    """TCP 端口级控制（Linux Landlock v4 原生支持，其他平台降级为全开/全关）。"""

    # --- 资源限制 ---
    max_processes: Optional[int] = None
    """最大子进程数。Windows Job 原生, Linux cgroups, macOS 不支持则忽略。"""

    max_memory_mb: Optional[int] = None
    """最大内存(MB)。Windows Job 原生, Linux cgroups, macOS 不支持则忽略。"""

    # --- 执行控制 ---
    timeout_seconds: int = 30
    env_vars: Dict[str, str] = field(default_factory=dict)
    env_mode: str = "inject"
    """'inject' = 追加到当前环境, 'allowlist' = 只传递声明的变量。"""

    # --- 平台透传 (escape hatch) ---
    platform_hints: Dict[str, Any] = field(default_factory=dict)
    """极少使用。透传平台原生参数，如 seatbelt_extra_rules / landlock_extra_flags。"""


@dataclass
class ExecutionResult:
    """sandbox.execute() 的返回值。"""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: int = 0
    sandbox_violation: Optional[str] = None


@dataclass
class SandboxCapability:
    """平台沙箱支持探测结果。启动时调用 probe_sandbox_support() 获取。"""

    supported: bool
    mode: SandboxMode
    reason: str  # 人类可读原因
    landlock_abi_version: int = 0  # Linux 专属：Landlock ABI 版本（0=不支持）


def _probe_linux_landlock() -> SandboxCapability:
    """探测 Linux Landlock 支持情况。

    检测步骤：
        1. 内核版本 >= 5.13
        2. /sys/kernel/security/lsm 包含 "landlock"
        3. 尝试 landlock_create_ruleset syscall 探测 ABI 版本
    """
    import os
    import struct
    import ctypes
    import ctypes.util

    # Step 1: 检查内核版本
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

    # Step 2: 检查 LSM 列表
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

    # Step 3: 探测 ABI 版本 via landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
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
        libc.syscall.argtypes = [ctypes.c_long, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        abi_version = libc.syscall(
            SYS_landlock_create_ruleset,
            None,  # attr = NULL
            0,     # size = 0
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
    """探测 macOS Seatbelt 支持情况。"""
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
    """探测 Windows WSL2 + Landlock 支持情况。

    检测步骤：
        1. wsl.exe 是否可用
        2. 是否有 WSL2 发行版
        3. WSL2 发行版内是否有 python3
        4. WSL2 发行版内核是否支持 Landlock
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
    """启动时探测当前平台沙箱支持情况。

    返回 SandboxCapability 描述是否支持沙箱隔离。
    如果不支持，mode 为 NONE，调用方应据此阻止 SANDBOX_FALLBACK 路径。
    """
    import sys

    if sys.platform == "darwin":
        return _probe_macos_seatbelt()
    elif sys.platform == "linux":
        return _probe_linux_landlock()
    elif sys.platform == "win32":
        return _probe_windows_wsl2()
    else:
        return SandboxCapability(
            supported=False,
            mode=SandboxMode.NONE,
            reason=f"Unsupported platform: {sys.platform}",
        )


def detect_platform_mode() -> SandboxMode:
    """根据当前 OS 自动选择沙箱模式。

    调用 probe_sandbox_support() 进行真实能力探测：
    如果平台不支持沙箱隔离，返回 NONE。
    """
    cap = probe_sandbox_support()
    return cap.mode
