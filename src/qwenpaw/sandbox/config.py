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


def detect_platform_mode() -> SandboxMode:
    """根据当前 OS 自动选择沙箱模式。"""
    import sys

    if sys.platform == "darwin":
        return SandboxMode.SEATBELT
    elif sys.platform == "linux":
        return SandboxMode.LANDLOCK
    elif sys.platform == "win32":
        return SandboxMode.WSL2
    else:
        return SandboxMode.NONE
