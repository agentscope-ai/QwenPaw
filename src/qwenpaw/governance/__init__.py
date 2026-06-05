# -*- coding: utf-8 -*-
"""Governance — ResourceGovernor stub (Phase 1).

Phase 1 策略：
  - assert_and_audit() 固定返回 ALLOW
  - compile_sandbox_config() 返回硬编码默认配置（只允许读写 workspace_dir）
  - 后续 Phase 2 填充真实的 PolicyRule 评估 + AuditLog

Usage:
    from qwenpaw.governance import ResourceGovernor

    governor = ResourceGovernor(workspace_dir="/path/to/project")
    governor.start()

    decision = governor.assert_and_audit(tool_call)
    sandbox_config = governor.compile_sandbox_config("agent-1", "session-1")
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from ..sandbox import (
    MountSpec,
    SandboxConfig,
    SandboxMode,
    detect_platform_mode,
)

logger = logging.getLogger(__name__)


class PolicyDecision(str, Enum):
    """策略裁决结果。"""

    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK = "ASK"
    NO_MATCH = "NO_MATCH"


class ResourceGovernor:
    """Governance 治理面聚合根。Phase 1 stub 实现。

    Phase 1 行为：
      - assert_and_audit(): 固定返回 ALLOW（不做策略评估）
      - compile_sandbox_config(): 返回只允许读写 workspace_dir 的固定配置
      - add_rule(): no-op

    生命周期由 Runtime 管理。
    """

    def __init__(self, workspace_dir: str):
        self._workspace_dir = workspace_dir
        self._started = False

    @property
    def workspace_dir(self) -> str:
        return self._workspace_dir

    def start(self) -> None:
        """启动 governance 服务。"""
        self._started = True
        logger.info("ResourceGovernor started (Phase 1 stub), workspace=%s", self._workspace_dir)

    def stop(self) -> None:
        """停止 governance 服务。"""
        self._started = False
        logger.info("ResourceGovernor stopped")

    def assert_and_audit(self, tool_call: Any) -> PolicyDecision:
        """策略评估 + 审计记录。

        Phase 1: 固定返回 ALLOW，不做任何评估。
        Phase 2: 接入 PolicyRule first-match-wins 评估 + AuditLog。
        """
        # Phase 1: always allow
        return PolicyDecision.ALLOW

    def compile_sandbox_config(
        self, agent_id: str, session_id: str
    ) -> SandboxConfig:
        """编译 sandbox 配置。

        Phase 1: 固定配置 — 只允许读写 workspace_dir + /tmp。
        Phase 2: 根据 policy allow 规则动态编译路径白名单。
        """
        return SandboxConfig(
            mode=detect_platform_mode(),
            workspace_dir=self._workspace_dir,
            mounts=[
                MountSpec(path=self._workspace_dir, writable=True),
                MountSpec(path="/tmp", writable=True),
            ],
            network_allow=["*"],  # Phase 1: 暂不限网络
            timeout_seconds=30,
        )

    def add_rule(self, rule: Any) -> None:
        """动态追加规则。Phase 1: no-op。"""
        logger.debug("add_rule called (Phase 1 stub, ignored): %s", rule)


__all__ = ["PolicyDecision", "ResourceGovernor"]
