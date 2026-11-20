# -*- coding: utf-8 -*-
"""UT for the tool_adapter approval-scope consumer (the lever).

``_ask_user_approval`` must pick the recorded rule target from the user's
chosen scope: SIMILAR → the generalized pattern, EXACT/None → the literal
target. This exercises that decision with a fake ApprovalService + governor
so no real model / HTTP / agentscope runtime is needed.
"""

from __future__ import annotations

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import FunctionTool, ToolChunk

from qwenpaw.app import approvals as approvals_mod
from qwenpaw.config import context as config_context
from qwenpaw.governance import generalize as generalize_mod, tool_adapter
from qwenpaw.governance.detectors import GuardFinding
from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernancePolicy,
    GovernanceRule,
    ToolCallSpec,
)
from qwenpaw.governance.resource_governor import ResourceGovernor
from qwenpaw.security.tool_guard.approval import (
    ApprovalDecision,
    ApprovalScope,
)


class _FakePending:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.scope: ApprovalScope | None = None


class _FakeApprovalService:
    """Stand-in for ApprovalService.

    ``wait_for_approval`` resolves APPROVED and stashes the chosen scope on
    the pending record — mirroring what ``resolve_request`` does for real.
    """

    def __init__(self, scope: ApprovalScope | None) -> None:
        self._scope = scope
        self._pending = _FakePending("fake-req-id")

    async def cancel_stale_pending_for_tool_call(
        self,
        *_a,
        **_kw,
    ):  # noqa: ANN
        return 0

    async def create_pending(self, **kwargs):  # noqa: ANN
        # Carry the display payload so we can assert on it too.
        self._pending.extra = kwargs.get("extra", {})
        return self._pending

    async def wait_for_approval(
        self,
        _request_id,
        _timeout_seconds,
    ):  # noqa: ANN
        self._pending.scope = self._scope
        return ApprovalDecision.APPROVED


class _FakeGovernor:
    def __init__(self) -> None:
        self.audits: list = []
        self.added: list[tuple[ToolCallSpec, str]] = []

    def audit(self, tc_spec, decision):  # noqa: ANN
        self.audits.append((tc_spec, decision))

    async def add_approved_rule(
        self,
        tc_spec,
        *,
        generalized_target,
    ):  # noqa: ANN
        self.added.append((tc_spec, generalized_target))
        return True

    def is_builtin_ask(self, _tc_spec):  # noqa: ANN
        return False


def _tc(target: str = "git status") -> ToolCallSpec:
    return ToolCallSpec(
        tool_name="Bash",
        target=target,
        agent_id="agent-1",
        session_id="session-1",
    )


async def _run_approval(
    scope: ApprovalScope | None,
    monkeypatch,
    source="No rule hit",
    builtin=False,
):
    """Drive ``_ask_user_approval`` with fakes; return (governor, pending)."""
    from qwenpaw.governance import tool_adapter

    fake_svc = _FakeApprovalService(scope)
    monkeypatch.setattr(
        tool_adapter,
        "get_approval_service",
        lambda: fake_svc,
        raising=False,
    )
    # Avoid the real LLM generalization round-trip. ``_ask_user_approval``
    # imports this lazily from ``.generalize`` inside the function body, so
    # the patch must land on the generalize module, not tool_adapter.
    import qwenpaw.governance.generalize as generalize_mod

    async def _fake_generalize(
        _tool_name,
        _target,
        _source,
        agent_id=None,
    ):  # noqa: ANN
        del agent_id
        return "git *"

    monkeypatch.setattr(
        generalize_mod,
        "generalize_target_for_approval",
        _fake_generalize,
        raising=False,
    )

    governor = _FakeGovernor()
    if builtin:
        governor.is_builtin_ask = lambda _tc_spec: True
    # ``_ask_user_approval`` imports get_approval_service lazily from
    # ..app.approvals; patch that path too.
    import qwenpaw.app.approvals as approvals_mod

    monkeypatch.setattr(
        approvals_mod,
        "get_approval_service",
        lambda: fake_svc,
        raising=False,
    )

    tc = _tc()
    await tool_adapter._ask_user_approval(
        governor=governor,
        tc_spec=tc,
        request_context={
            "user_id": "u",
            "channel": "console",
            "root_session_id": "session-1",
            "root_agent_id": "agent-1",
            "tool_call_id": "tc-1",
        },
        source=source,
    )
    return governor, fake_svc._pending


class TestApprovalScopeConsumer:
    """The consumer picks the recorded target from the chosen scope."""

    async def test_similar_records_pattern(self, monkeypatch):
        governor, _pending = await _run_approval(
            ApprovalScope.SIMILAR,
            monkeypatch,
        )
        assert governor.added, "no rule was recorded"
        _tc_spec, target = governor.added[0]
        assert target == "git *"
        # Audit reason carries the scope label.
        _spec, decision = governor.audits[-1]
        assert "similar" in decision.reason

    async def test_jev_approval_is_one_time(self, monkeypatch):
        governor, _pending = await _run_approval(
            ApprovalScope.SIMILAR,
            monkeypatch,
            source="jev",
        )
        assert governor.added == []
        assert governor.audits[-1][1].action.value == "allow"

    async def test_exact_records_literal(self, monkeypatch):
        governor, _pending = await _run_approval(
            ApprovalScope.EXACT,
            monkeypatch,
        )
        _tc_spec, target = governor.added[0]
        assert target == "git status"
        _spec, decision = governor.audits[-1]
        assert "exact" in decision.reason

    async def test_none_scope_defaults_to_exact(self, monkeypatch):
        """No scope (IM channel / CLI) → records the literal target."""
        governor, _pending = await _run_approval(None, monkeypatch)
        _tc_spec, target = governor.added[0]
        assert target == "git status"
        _spec, decision = governor.audits[-1]
        assert "exact" in decision.reason

    async def test_display_payload_carries_both_targets(self, monkeypatch):
        _governor, pending = await _run_approval(
            ApprovalScope.SIMILAR,
            monkeypatch,
        )
        display = pending.extra["display"]
        assert display["is_generalized"] is True
        assert display["exact_target"] == "git status"
        assert display["similar_target"] == "git *"
        assert display["approval_behavior"] == "session_rule"

    async def test_once_metadata_for_decision_model(self, monkeypatch):
        """Decision-model approvals must not advertise saved rules."""
        for source in ("jev", "decision_model"):
            _, pending = await _run_approval(
                ApprovalScope.EXACT,
                monkeypatch,
                source=source,
            )
            assert pending.extra["display"]["approval_behavior"] == "once"

    async def test_once_metadata_for_builtin_ask(self, monkeypatch):
        """Builtin ASK approvals must not advertise session grants."""
        _, pending = await _run_approval(
            ApprovalScope.EXACT,
            monkeypatch,
            builtin=True,
        )
        assert pending.extra["display"]["approval_behavior"] == "once"

    async def test_strict_metadata_preserves_repeated_confirmation(
        self,
        monkeypatch,
    ):
        """Strict mode must not promise that later calls skip approval."""
        _, pending = await _run_approval(
            ApprovalScope.EXACT,
            monkeypatch,
            source="STRICT mode",
        )
        assert pending.extra["display"]["approval_behavior"] == "strict"


@pytest.mark.parametrize(
    ("policy_level", "session_level", "f1_active"),
    [
        ("strict", None, False),
        ("smart", "strict", False),
        ("off", "off", True),
    ],
)
@pytest.mark.parametrize(
    "source",
    ["fallback", "detection_rules", "user_rules"],
)
@pytest.mark.parametrize("sandbox_retry", [False, True])
async def test_strict_metadata_uses_evaluated_level(
    monkeypatch,
    tmp_path,
    policy_level,
    session_level,
    f1_active,
    source,
    sandbox_retry,
):
    """Real policy sources must preserve strict and temporary F1 levels."""
    policy = GovernancePolicy(execution_level=policy_level)
    spec = ToolCallSpec(
        "Read",
        "report.txt",
        "agent-1",
        "session-1",
    )
    findings = []
    if source == "detection_rules":
        findings.append(
            GuardFinding(
                id="strict-finding",
                rule_id="STRICT_TEST",
                category="resource_abuse",
                severity="INFO",
                title="Review file access",
                description="File access requires confirmation",
                tool_name=spec.tool_name,
                detector="pattern_detector",
            ),
        )
    elif source == "user_rules":
        policy.add_rule(
            GovernanceRule(
                match="Read(*)",
                action=GovernanceAction.ASK,
            ),
        )
    monkeypatch.setattr(policy, "_deep_security_scan", lambda *_: findings)
    governor = ResourceGovernor(
        str(tmp_path),
        governance_dir=str(tmp_path / "governance"),
    )
    governor._policy = policy
    monkeypatch.setattr(governor, "audit", lambda *_: None)
    monkeypatch.setattr(governor, "add_rule", policy.add_rule)
    service = _FakeApprovalService(ApprovalScope.EXACT)
    monkeypatch.setattr(
        approvals_mod,
        "get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        generalize_mod,
        "generalize_target_for_approval",
        AsyncMock(return_value="*.txt"),
    )
    monkeypatch.setattr(
        config_context,
        "is_f1_active_for_session",
        lambda session_id: f1_active and session_id == spec.session_id,
    )
    request_context = {"session_id": spec.session_id}
    if session_level is not None:
        request_context["approval_level"] = session_level
    tool = SimpleNamespace(
        _qp_governor=governor,
        _qp_request_context=request_context,
        _build_tc_spec=lambda: spec,
    )

    decision = await tool_adapter._policy_tool_check_permissions(tool, {})

    assert decision.behavior.value == "allow"
    if sandbox_retry:
        denied = ToolChunk(
            is_last=True,
            state=ToolResultState.DENIED,
            content=[
                TextBlock(
                    type="text",
                    text="Sandbox violation: file access",
                ),
            ],
        )
        monkeypatch.setattr(
            FunctionTool,
            "__call__",
            AsyncMock(side_effect=[denied, "retried"]),
        )
        assert await tool_adapter._policy_tool_call(tool) == "retried"

    display = service._pending.extra["display"]
    assert display["tool_source"] == source
    assert display["approval_behavior"] == "strict"
    assert display["is_generalized"] is True
    expected_level = policy_level if f1_active else "strict"
    assert governor.policy.execution_level == expected_level
