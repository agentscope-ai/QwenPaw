# -*- coding: utf-8 -*-
"""UT for approval scope plumbing (EXACT vs SIMILAR).

Covers the new ``ApprovalScope`` enum, ``ApprovalService.resolve_request``
staking scope on the pending record, and ``approval_display_fields``
surfacing the console gating fields.
"""
from __future__ import annotations

# pylint: disable=protected-access

import asyncio

from qwenpaw.app.approvals.display import approval_display_fields
from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
from qwenpaw.security.tool_guard.approval import (
    ApprovalDecision,
    ApprovalScope,
)
from qwenpaw.security.tool_guard.models import (
    GuardSeverity,
    ToolGuardResult,
)


def _make_pending(request_id: str = "req-1") -> PendingApproval:
    """Build a PendingApproval directly (bypasses create_pending)."""
    loop = asyncio.get_event_loop()
    return PendingApproval(
        request_id=request_id,
        session_id="s",
        root_session_id="s",
        owner_agent_id="a",
        user_id="u",
        channel="console",
        agent_id="a",
        tool_name="Bash",
        created_at=0.0,
        future=loop.create_future(),
    )


class TestApprovalScopeEnum:
    """ApprovalScope enum basics."""

    def test_values(self):
        assert ApprovalScope.EXACT.value == "exact"
        assert ApprovalScope.SIMILAR.value == "similar"

    def test_is_str_enum(self):
        assert ApprovalScope.SIMILAR == "similar"
        assert isinstance(ApprovalScope.EXACT, str)

    def test_construct_from_string(self):
        """Router/command paths build the enum from a user-supplied string."""
        assert ApprovalScope("exact") is ApprovalScope.EXACT
        assert ApprovalScope("similar") is ApprovalScope.SIMILAR


class TestResolveRequestStashesScope:
    """resolve_request writes scope onto the pending record so the
    governance consumer (tool_adapter) can pick the rule target."""

    async def test_similar_scope_is_stashed(self):
        svc = ApprovalService()
        pending = _make_pending()
        svc._pending[pending.request_id] = pending

        resolved = await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
            scope=ApprovalScope.SIMILAR,
        )

        assert resolved is pending
        assert resolved.scope is ApprovalScope.SIMILAR
        # The future is resolved with the plain decision (scope is orthogonal).
        assert resolved.future.result() is ApprovalDecision.APPROVED

    async def test_none_scope_defaults_to_exact_downstream(self):
        """No scope passed (IM channels / CLI) → scope stays None; the
        consumer treats None as EXACT. Pending is still resolved."""
        svc = ApprovalService()
        pending = _make_pending()
        svc._pending[pending.request_id] = pending

        resolved = await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
        )

        assert resolved.scope is None
        assert resolved.future.result() is ApprovalDecision.APPROVED

    async def test_exact_scope_stashed(self):
        svc = ApprovalService()
        pending = _make_pending()
        svc._pending[pending.request_id] = pending

        resolved = await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
            scope=ApprovalScope.EXACT,
        )
        assert resolved.scope is ApprovalScope.EXACT

    async def test_scope_ignored_on_deny(self):
        """Scope is meaningless for a denial, but resolve still accepts it
        without error and resolves the future as DENIED."""
        svc = ApprovalService()
        pending = _make_pending()
        svc._pending[pending.request_id] = pending

        resolved = await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.DENIED,
            scope=ApprovalScope.SIMILAR,
        )
        assert resolved.future.result() is ApprovalDecision.DENIED


class _FakePending:
    """Minimal stand-in exposing ``extra`` + ``tool_name`` for display."""

    def __init__(self, display: dict | None) -> None:
        self.extra = {"display": display} if display is not None else {}
        self.tool_name = "Bash"


class TestApprovalDisplayFields:
    """approval_display_fields surfaces the scope-choice gating fields."""

    def test_generalized_targets_surface(self):
        pending = _FakePending(
            {
                "tool_name": "Bash",
                "tool_source": "No rule hit",
                "exact_target": "git status",
                "similar_target": "git *",
                "is_generalized": True,
            },
        )
        fields = approval_display_fields(pending)
        assert fields["exact_target"] == "git status"
        assert fields["similar_target"] == "git *"
        assert fields["is_generalized"] is True
        assert fields["tool_display_name"] == "Bash"

    def test_not_generalized(self):
        pending = _FakePending(
            {
                "tool_name": "Bash",
                "tool_source": "builtin_rules",
                "exact_target": "git status",
                "similar_target": "git status",
                "is_generalized": False,
            },
        )
        fields = approval_display_fields(pending)
        assert fields["is_generalized"] is False

    def test_missing_display_defaults_safely(self):
        """No display dict at all → safe defaults, is_generalized False."""
        pending = _FakePending(None)
        fields = approval_display_fields(pending)
        assert fields["is_generalized"] is False
        assert fields["exact_target"] == ""
        assert fields["similar_target"] == ""
        assert fields["tool_display_name"] == "Bash"
        assert fields["tool_source"] == "No rule hit"


class TestToolGuardResultUnchanged:
    """Sanity: ToolGuardResult still constructs (display plumbing imports)."""

    def test_construct(self):
        result = ToolGuardResult(
            tool_name="Bash",
            params={},
            findings=[],
        )
        assert result.findings_count == 0
        assert result.max_severity == GuardSeverity.SAFE
