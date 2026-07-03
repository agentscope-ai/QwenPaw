# -*- coding: utf-8 -*-
"""UT for the tool_adapter approval-scope consumer (the lever).

``_ask_user_approval`` must pick the recorded rule target from the user's
chosen scope: SIMILAR → the generalized pattern, EXACT/None → the literal
target. This exercises that decision with a fake ApprovalService + governor
so no real model / HTTP / agentscope runtime is needed.
"""
from __future__ import annotations

# pylint: disable=protected-access

from qwenpaw.governance.policy import ToolCallSpec
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


async def _run_approval(scope: ApprovalScope | None, monkeypatch):
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
        source="No rule hit",
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
