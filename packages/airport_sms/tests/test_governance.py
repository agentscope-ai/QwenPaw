"""治理门行为测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airport_sms.domain import CaseId, RiskLevel, Role, new_draft
from airport_sms.governance import (
    ApprovalService,
    GovernanceAction,
    GovernancePolicy,
    GovernanceRule,
    Governor,
)


def test_builtin_before_user() -> None:
    policy = GovernancePolicy(
        builtin_rules=[
            GovernanceRule("notify_ops", GovernanceAction.ASK, "hb")
        ],
        user_rules=[
            GovernanceRule("notify_ops", GovernanceAction.ALLOW, "user")
        ],
    )
    d = policy.evaluate("notify_ops")
    assert d.source == "builtin_rules"
    assert d.action is GovernanceAction.ASK


def test_unknown_tool_denied() -> None:
    d = GovernancePolicy().evaluate("not_a_tool")
    assert d.action is GovernanceAction.DENY


def test_high_risk_close_asks() -> None:
    d = GovernancePolicy().evaluate(
        "close_case", risk_level=RiskLevel.EXTREME
    )
    assert d.action is GovernanceAction.ASK


def test_approval_timeout_leaves_case() -> None:
    case = new_draft(case_id=CaseId("c1"), hazard="h", location="l")
    gov = Governor(GovernancePolicy())
    result = gov.invoke("submit_case", lambda: None, case=case)
    assert result.approval_id
    state_before = case.state
    fixed = datetime(2020, 1, 1, tzinfo=timezone.utc)
    gov.approvals.now_factory = lambda: fixed + timedelta(hours=1)
    gov.approvals.pending[result.approval_id].created_at = fixed
    gov.approvals.pending[result.approval_id].ttl = timedelta(minutes=1)
    _, action = gov.approvals.expire(result.approval_id)
    assert action is GovernanceAction.DENY
    assert case.state is state_before


def test_oneshot_approve_no_permanent_allow() -> None:
    policy = GovernancePolicy()
    before = len(policy.user_rules)
    policy.add_user_rule(
        GovernanceRule("submit_case", GovernanceAction.ALLOW, "perm")
    )
    assert len(policy.user_rules) == before
    assert policy.evaluate("submit_case").action is GovernanceAction.ASK


def test_audit_stores_source() -> None:
    gov = Governor(GovernancePolicy())
    gov.invoke("search_manual", lambda: "ok")
    assert gov.audit[-1].source in {"builtin_rules", "default", "user_rules"}


def test_off_still_enforces_handbook_deny() -> None:
    policy = GovernancePolicy(
        builtin_rules=[
            GovernanceRule("notify_ops", GovernanceAction.DENY, "hb")
        ]
    )
    assert policy.evaluate("notify_ops").action is GovernanceAction.DENY


def test_notify_ops_never_silent_allow() -> None:
    d = GovernancePolicy().evaluate("notify_ops")
    assert d.action in {GovernanceAction.ASK, GovernanceAction.DENY}


def test_governor_allow_executes() -> None:
    gov = Governor(
        GovernancePolicy(
            builtin_rules=[
                GovernanceRule("search_manual", GovernanceAction.ALLOW, "ok")
            ]
        )
    )
    result = gov.invoke("search_manual", lambda: 42)
    assert result.value == 42
    assert result.decision.action is GovernanceAction.ALLOW


def test_approval_service_decide() -> None:
    svc = ApprovalService()
    req = svc.ask(tool_name="submit_case", case_id="c1")
    decided, action = svc.decide(req.id, approve=True)
    assert decided.status.value == "approved"
    assert action is GovernanceAction.ALLOW
