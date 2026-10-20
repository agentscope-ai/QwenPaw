# -*- coding: utf-8 -*-
"""Decision-model review preserves governance and sandboxing."""

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernanceDecision,
    GovernancePolicy,
    ToolCallSpec,
)
from qwenpaw.governance import tool_adapter
from qwenpaw.security.decision_model import DecisionModelAssessment


def _fake_tool(action, *, approval_origin="unknown", tool_name="Write"):
    spec = ToolCallSpec(
        tool_name,
        "notes.txt",
        "agent",
        "session",
        {"content": "x"},
    )
    audits = []
    policy = SimpleNamespace(execution_level="auto")
    governor = SimpleNamespace(
        policy=policy,
        assert_policy=lambda _spec: GovernanceDecision(
            action,
            "baseline",
            sandbox_config="sandbox"
            if action is GovernanceAction.SANDBOX_FALLBACK
            else None,
            approval_origin=approval_origin,
        ),
        audit=lambda _spec, decision: audits.append(decision),
        sandbox_usable=True,
        compile_sandbox_config=lambda _spec: "compiled sandbox",
    )
    tool = SimpleNamespace(
        _qp_governor=governor,
        _qp_request_context={"approval_level": "JEV", "session_id": "session"},
        _build_tc_spec=lambda: spec,
    )
    return tool, audits


@pytest.mark.asyncio
async def test_deterministic_deny_never_calls_decision_model(monkeypatch):
    tool, audits = _fake_tool(GovernanceAction.DENY)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("Decision model must not be called after deny")

    monkeypatch.setattr(
        "qwenpaw.security.decision_model.assess_tool_call",
        unexpected,
    )
    result = await tool_adapter._policy_tool_check_permissions(tool, {})
    assert result.behavior.value == "deny"
    assert audits[0].action is GovernanceAction.DENY


@pytest.mark.asyncio
async def test_model_escalates_sandbox_fallback_without_dropping_sandbox(
    monkeypatch,
):
    tool, audits = _fake_tool(GovernanceAction.SANDBOX_FALLBACK)

    async def risky(*_args, **kwargs):
        assert kwargs["sandboxed"] is True
        return DecisionModelAssessment(
            True,
            "Decision model: confirmation required",
        )

    async def approve(**kwargs):
        assert kwargs["source"] == "decision_model"
        return "approved"

    monkeypatch.setattr(
        "qwenpaw.security.decision_model.assess_tool_call",
        risky,
    )
    monkeypatch.setattr(tool_adapter, "_ask_user_approval", approve)
    result = await tool_adapter._policy_tool_check_permissions(tool, {})
    assert result == "approved"
    assert audits[0].action is GovernanceAction.ASK
    assert tool._qp_sandbox_mode is True
    assert tool._qp_sandbox_config == "sandbox"
    assert tool._qp_decision_model_sandbox_required is True


@pytest.mark.asyncio
async def test_decision_model_can_relax_only_proven_soft_ask(monkeypatch):
    tool, audits = _fake_tool(
        GovernanceAction.ASK,
        approval_origin="soft_risk",
    )

    async def safe(*_args, **kwargs):
        assert kwargs["baseline_ask"] is True
        assert kwargs["agent_id"] == "agent"
        return DecisionModelAssessment(
            False,
            "Decision model: low-risk assessment",
        )

    monkeypatch.setattr(
        "qwenpaw.security.decision_model.assess_tool_call",
        safe,
    )
    result = await tool_adapter._policy_tool_check_permissions(tool, {})
    assert result.behavior.value == "allow"
    assert audits[0].action is GovernanceAction.ALLOW
    assert audits[0].source == "decision_model"


@pytest.mark.asyncio
async def test_explicit_ask_does_not_call_decision_model(monkeypatch):
    tool, audits = _fake_tool(
        GovernanceAction.ASK,
        approval_origin="mandatory",
    )

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("explicit approval must not be relaxed")

    async def approve(**_kwargs):
        return "approved"

    monkeypatch.setattr(
        "qwenpaw.security.decision_model.assess_tool_call",
        unexpected,
    )
    monkeypatch.setattr(tool_adapter, "_ask_user_approval", approve)
    result = await tool_adapter._policy_tool_check_permissions(tool, {})
    assert result == "approved"
    assert audits[0].action is GovernanceAction.ASK


def test_only_unmodified_bundled_findings_are_soft(monkeypatch):
    from qwenpaw.governance import policy as policy_module

    bundled = policy_module.DetectionRuleConfig(id="bundled")
    policy = GovernancePolicy(execution_level="jev", detection_rules=[bundled])
    monkeypatch.setattr(
        policy_module,
        "_get_default_detection_rules",
        lambda: [bundled],
    )
    monkeypatch.setattr(policy, "_merge_config_rules", lambda: ([bundled], {}))
    finding = SimpleNamespace(
        rule_id="bundled",
        detector="pattern_detector",
        severity="HIGH",
        description="risk",
    )
    spec = ToolCallSpec("Write", "notes.txt", "agent", "session")
    decision = policy._apply_execution_level_fallback(spec, [finding])
    assert decision.action is GovernanceAction.ASK
    assert decision.approval_origin == "soft_risk"

    modified = policy_module.DetectionRuleConfig(
        id="bundled",
        severity="CRITICAL",
    )
    monkeypatch.setattr(
        policy,
        "_merge_config_rules",
        lambda: ([modified], {}),
    )
    decision = policy._apply_execution_level_fallback(spec, [finding])
    assert decision.approval_origin == "mandatory"


@pytest.mark.asyncio
async def test_soft_shell_ask_never_becomes_unsandboxed_allow(monkeypatch):
    tool, audits = _fake_tool(
        GovernanceAction.ASK,
        approval_origin="soft_risk",
        tool_name="Bash",
    )

    async def safe(*_args, **kwargs):
        assert kwargs["sandboxed"] is True
        return DecisionModelAssessment(
            False,
            "Decision model: low-risk assessment",
        )

    monkeypatch.setattr(
        "qwenpaw.security.decision_model.assess_tool_call",
        safe,
    )
    result = await tool_adapter._policy_tool_check_permissions(tool, {})
    assert result.behavior.value == "allow"
    assert audits[0].action is GovernanceAction.ALLOW
    assert tool._qp_sandbox_mode is True
    assert tool._qp_sandbox_config == "compiled sandbox"
    assert tool._qp_decision_model_sandbox_required is True


@pytest.mark.asyncio
async def test_soft_shell_ask_stays_ask_without_sandbox(monkeypatch):
    tool, audits = _fake_tool(
        GovernanceAction.ASK,
        approval_origin="soft_risk",
        tool_name="Bash",
    )
    tool._qp_governor.sandbox_usable = False

    async def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "Decision model must not relax a shell ASK without sandbox",
        )

    async def approve(**_kwargs):
        return "approved"

    monkeypatch.setattr(
        "qwenpaw.security.decision_model.assess_tool_call",
        unexpected,
    )
    monkeypatch.setattr(tool_adapter, "_ask_user_approval", approve)
    assert (
        await tool_adapter._policy_tool_check_permissions(tool, {})
        == "approved"
    )
    assert audits[0].action is GovernanceAction.ASK
