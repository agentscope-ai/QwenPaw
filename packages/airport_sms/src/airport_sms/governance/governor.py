"""工具入口治理包装：AgentScope 无法绕过。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from airport_sms.domain.case import Case, RiskLevel
from airport_sms.governance.approval import ApprovalService
from airport_sms.governance.policy import (
    GovernanceAction,
    GovernancePolicy,
    PolicyDecision,
)


@dataclass
class GovernedResult:
    """治理后的调用结果。"""

    decision: PolicyDecision
    value: Any = None
    case: Case | None = None
    approval_id: str | None = None


@dataclass
class Governor:
    """在每次工具调用前评估策略。"""

    policy: GovernancePolicy
    approvals: ApprovalService = field(default_factory=ApprovalService)
    audit: list[PolicyDecision] = field(default_factory=list)

    def invoke(
        self,
        tool_name: str,
        fn: Callable[..., Any],
        *,
        case: Case | None = None,
        risk_level: RiskLevel | None = None,
        **kwargs: Any,
    ) -> GovernedResult:
        """评估后执行或挂起 ask。"""
        risk = risk_level
        if risk is None and case is not None:
            risk = case.risk_level
        decision = self.policy.evaluate(tool_name, risk_level=risk)
        self.audit.append(decision)

        if decision.action is GovernanceAction.DENY:
            return GovernedResult(decision=decision, case=case)

        if decision.action is GovernanceAction.ASK:
            case_id = str(case.id) if case is not None else ""
            req = self.approvals.ask(tool_name=tool_name, case_id=case_id)
            return GovernedResult(
                decision=decision,
                case=case,
                approval_id=req.id,
            )

        value = fn(**kwargs)
        return GovernedResult(decision=decision, value=value, case=case)


__all__ = ["GovernedResult", "Governor"]
