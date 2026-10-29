"""工具沙箱：仅约束代码执行类工具，关闭案件归治理。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SandboxAction(str, Enum):
    """沙箱裁决。"""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class SandboxDecision:
    """沙箱结果。violation 后禁止无沙箱重跑。"""

    action: SandboxAction
    reason: str
    allow_unsandboxed_rerun: bool = False


class Sandbox:
    """SMS 写工具违规后不得自动升到无沙箱。"""

    def __init__(self, *, enforce: bool = True) -> None:
        self.enforce = enforce
        self._violations: set[str] = set()

    def check(self, tool_name: str, *, readonly: bool = False) -> SandboxDecision:
        """只读工具可用 no-op 放行。"""
        if readonly or not self.enforce:
            return SandboxDecision(SandboxAction.ALLOW, "noop")
        if tool_name in self._violations:
            return SandboxDecision(
                SandboxAction.DENY,
                "prior violation",
                allow_unsandboxed_rerun=False,
            )
        return SandboxDecision(SandboxAction.ALLOW, "sandboxed")

    def record_violation(self, tool_name: str) -> SandboxDecision:
        """记录违规并拒绝无沙箱重跑。"""
        self._violations.add(tool_name)
        return SandboxDecision(
            SandboxAction.DENY,
            "violation",
            allow_unsandboxed_rerun=False,
        )


__all__ = ["Sandbox", "SandboxAction", "SandboxDecision"]
