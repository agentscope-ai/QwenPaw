# -*- coding: utf-8 -*-
"""Sandbox configuration and result types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SandboxMode(str, Enum):
    """沙箱隔离模式。"""

    SEATBELT = "seatbelt"  # macOS sandbox-exec
    LANDLOCK = "landlock"  # Linux (future)
    WSL2 = "wsl2"          # Windows (future)
    NONE = "none"          # 不隔离，直接执行


@dataclass
class MountSpec:
    """一条路径权限声明。writable=True 表示可读写，否则只读。"""

    path: str
    writable: bool = False


@dataclass
class SandboxConfig:
    """sandbox 的完整约束配置。白名单模型：未列入 = 拒绝。"""

    mode: SandboxMode
    workspace_dir: str
    mounts: List[MountSpec] = field(default_factory=list)
    network_allow: List[str] = field(default_factory=list)
    timeout_seconds: int = 30
    env_vars: Dict[str, str] = field(default_factory=dict)


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
