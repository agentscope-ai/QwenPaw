"""SMS 治理策略：builtin 先于 user 的先匹配。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from airport_sms.domain.case import RiskLevel
from airport_sms.tools.registry import ToolRegistry, build_default_registry


class GovernanceAction(str, Enum):
    """仅允许三种动作。"""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class GovernanceRule:
    """一条规则：按工具名匹配。"""

    tool_name: str
    action: GovernanceAction
    reason: str
    match_all: bool = False

    def matches(self, tool_name: str) -> bool:
        """是否命中该工具。"""
        if self.match_all:
            return True
        return self.tool_name == tool_name


@dataclass(frozen=True)
class PolicyDecision:
    """策略裁决。"""

    action: GovernanceAction
    source: str
    reason: str


HANDBOOK_ASK_TOOLS = frozenset(
    {
        "submit_case",
        "change_risk",
        "escalate",
        "notify_ops",
        "close_case",
    }
)


def default_builtin_rules() -> list[GovernanceRule]:
    """手册层 builtin：高风险动作一律 ask。"""
    rules = [
        GovernanceRule(name, GovernanceAction.ASK, "handbook ask")
        for name in sorted(HANDBOOK_ASK_TOOLS)
    ]
    return rules


@dataclass
class GovernancePolicy:
    """两层策略。builtin_rules 扫描完再扫 user_rules。"""

    builtin_rules: list[GovernanceRule] = field(
        default_factory=default_builtin_rules
    )
    user_rules: list[GovernanceRule] = field(default_factory=list)
    tool_registry: ToolRegistry = field(default_factory=build_default_registry)

    def evaluate(
        self,
        tool_name: str,
        *,
        risk_level: RiskLevel | None = None,
    ) -> PolicyDecision:
        """先匹配 wins。未知工具 deny。"""
        try:
            self.tool_registry.get(tool_name)
        except Exception:
            return PolicyDecision(
                GovernanceAction.DENY, "unknown_tool", "unknown tool"
            )

        for rule in self.builtin_rules:
            if rule.matches(tool_name):
                action = rule.action
                if (
                    tool_name == "close_case"
                    and risk_level is RiskLevel.EXTREME
                    and action is GovernanceAction.ALLOW
                ):
                    action = GovernanceAction.ASK
                return PolicyDecision(action, "builtin_rules", rule.reason)

        for rule in self.user_rules:
            if rule.matches(tool_name):
                return PolicyDecision(
                    rule.action, "user_rules", rule.reason
                )

        return PolicyDecision(
            GovernanceAction.ALLOW, "default", "no rule matched"
        )

    def add_user_rule(self, rule: GovernanceRule) -> None:
        """去重后插入 user_rules 头部。不能绕过 handbook ask 目标。"""
        if rule.tool_name in HANDBOOK_ASK_TOOLS and rule.action is GovernanceAction.ALLOW:
            # 拒绝写入永久 allow，保持 handbook ask
            return
        self.user_rules = [
            r
            for r in self.user_rules
            if not (
                r.tool_name == rule.tool_name
                and r.action == rule.action
            )
        ]
        self.user_rules.insert(0, rule)


__all__ = [
    "GovernanceAction",
    "GovernancePolicy",
    "GovernanceRule",
    "HANDBOOK_ASK_TOOLS",
    "PolicyDecision",
    "default_builtin_rules",
]
