# -*- coding: utf-8 -*-
"""Unit tests for ``ApprovalService``.

Covers the full approval lifecycle (create → resolve / cancel / timeout /
GC) and the cross-session / cross-agent scoping rules that prevent an
approval issued for one conversation tree from leaking into another.

Scope plumbing (EXACT vs SIMILAR) is exercised in
``tests/unit/app/test_approval_scope.py`` and intentionally not repeated
here.
"""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,unused-variable  # noqa: E501

import asyncio
import time

import pytest

from qwenpaw.app.approvals.models import ApprovalRequestSummary
from qwenpaw.app.approvals.service import (
    ApprovalService,
    PendingApproval,
    _GC_MAX_PENDING,
    get_approval_service,
)
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pending(
    request_id: str = "req-1",
    *,
    session_id: str = "s1",
    root_session_id: str = "s1",
    agent_id: str = "agent-A",
    owner_agent_id: str = "agent-A",
    tool_name: str = "Bash",
    extra: dict | None = None,
    created_at: float | None = None,
) -> PendingApproval:
    """Build a PendingApproval directly (bypasses create_pending).

    Uses the running loop when called from a coroutine, otherwise falls
    back to a fresh loop so the future object is constructible from sync
    test contexts (e.g. the GC test).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    return PendingApproval(
        request_id=request_id,
        session_id=session_id,
        root_session_id=root_session_id,
        owner_agent_id=owner_agent_id,
        user_id="u1",
        channel="console",
        agent_id=agent_id,
        tool_name=tool_name,
        created_at=time.time() if created_at is None else created_at,
        future=loop.create_future(),
        extra=dict(extra or {}),
    )


def _make_result(
    tool_name: str = "Bash",
    *,
    severity: GuardSeverity = GuardSeverity.HIGH,
    findings_count: int = 1,
) -> ToolGuardResult:
    """Build a ToolGuardResult with the requested finding count."""
    findings = [
        GuardFinding(
            id=f"f-{i}",
            rule_id=f"rule-{i}",
            category=GuardThreatCategory.CODE_EXECUTION,
            severity=severity,
            title="t",
            description="d",
            tool_name=tool_name,
        )
        for i in range(findings_count)
    ]
    return ToolGuardResult(tool_name=tool_name, params={}, findings=findings)


def _seed_pending(
    svc: ApprovalService,
    pending: PendingApproval,
) -> PendingApproval:
    """Insert a PendingApproval straight into the store."""
    svc._pending[pending.request_id] = pending
    return pending


# ---------------------------------------------------------------------------
# create_pending
# ---------------------------------------------------------------------------


async def test_create_pending_stores_record_and_severity_from_result():
    svc = ApprovalService()
    pending = await svc.create_pending(
        session_id="s1",
        root_session_id="root-1",
        owner_agent_id="agent-A",
        user_id="u1",
        channel="console",
        agent_id="agent-A",
        tool_name="Bash",
        result=_make_result("Bash", severity=GuardSeverity.HIGH),
    )

    assert pending.request_id  # uuid4
    assert pending.session_id == "s1"
    assert pending.root_session_id == "root-1"
    assert pending.owner_agent_id == "agent-A"
    assert pending.agent_id == "agent-A"
    assert pending.severity == "HIGH"
    assert pending.findings_count == 1
    assert pending.status == "pending"
    assert pending.scope is None
    # Stored under the request_id and retrievable.
    assert await svc.get_request(pending.request_id) is pending


async def test_create_pending_console_channel_skips_channel_notify():
    """Console channel must not fire-and-forget a channel notification."""
    svc = ApprovalService()
    pending = await svc.create_pending(
        session_id="s",
        root_session_id="s",
        owner_agent_id="a",
        user_id="u",
        channel="console",
        agent_id="a",
        tool_name="Bash",
        result=_make_result(),
    )
    # No _channel_instance was attached and no asyncio task was created.
    assert pending.extra.get("_channel_instance") is None


# ---------------------------------------------------------------------------
# create_pending_summary
# ---------------------------------------------------------------------------


async def test_create_pending_summary_propagates_summary_fields():
    svc = ApprovalService()
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="driver:http:Bash",
        severity="high",
        findings_count=3,
        result_summary="requires approval for invoke.",
        payload={"display": {"tool_name": "Bash"}},
    )
    pending = await svc.create_pending_summary(
        session_id="s",
        root_session_id="root",
        owner_agent_id="a",
        user_id="u",
        channel="console",
        agent_id="a",
        summary=summary,
    )
    assert pending.tool_name == "driver:http:Bash"
    assert pending.severity == "high"
    assert pending.findings_count == 3
    assert pending.result_summary == "requires approval for invoke."
    # source_type and payload are merged into extra, extra overrides payload.
    assert pending.extra["source_type"] == "driver_policy"
    assert pending.extra["display"] == {"tool_name": "Bash"}


async def test_create_pending_summary_extra_overrides_payload_keys():
    """Caller-supplied ``extra`` must win over ``summary.payload`` when the
    same key is present in both (merge order: payload first, then extra)."""
    svc = ApprovalService()
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="bash",
        payload={"display": {"tool_name": "Bash"}, "k": "from-payload"},
    )
    pending = await svc.create_pending_summary(
        session_id="s",
        root_session_id="root",
        owner_agent_id="a",
        user_id="u",
        channel="console",
        agent_id="a",
        summary=summary,
        extra={"k": "from-extra", "tag": "extra"},
    )
    assert pending.extra["k"] == "from-extra"
    assert pending.extra["tag"] == "extra"
    # payload-only key still present.
    assert pending.extra["display"] == {"tool_name": "Bash"}


# ---------------------------------------------------------------------------
# resolve_request
# ---------------------------------------------------------------------------


async def test_resolve_request_unknown_id_returns_none():
    svc = ApprovalService()
    resolved = await svc.resolve_request(
        "does-not-exist",
        ApprovalDecision.APPROVED,
    )
    assert resolved is None


async def test_resolve_request_pops_record_and_sets_status():
    svc = ApprovalService()
    pending = _seed_pending(svc, _make_pending("req-p"))
    resolved = await svc.resolve_request(
        "req-p",
        ApprovalDecision.DENIED,
    )
    assert resolved is pending
    assert resolved.status == ApprovalDecision.DENIED.value
    assert resolved.resolved_at is not None
    # Already popped from the pending store.
    assert await svc.get_request("req-p") is None
    # Future was resolved with the decision.
    assert pending.future.result() is ApprovalDecision.DENIED


async def test_resolve_request_already_resolved_future_is_safe():
    """If the future was already resolved (e.g. duplicate approve), the
    service must not raise — it simply no-ops the second set_result."""
    svc = ApprovalService()
    pending = _seed_pending(svc, _make_pending("req-d"))
    pending.future.set_result(ApprovalDecision.APPROVED)
    resolved = await svc.resolve_request("req-d", ApprovalDecision.DENIED)
    assert resolved is pending
    # The first decision wins because the future was already done.
    assert resolved.future.result() is ApprovalDecision.APPROVED


# ---------------------------------------------------------------------------
# lookup helpers (FIFO, scope isolation)
# ---------------------------------------------------------------------------


async def test_get_pending_by_session_returns_oldest_first():
    svc = ApprovalService()
    older = _seed_pending(
        svc,
        _make_pending("old", session_id="s", created_at=10.0),
    )
    _seed_pending(
        svc,
        _make_pending("new", session_id="s", created_at=20.0),
    )
    found = await svc.get_pending_by_session("s")
    assert found is older
    assert await svc.get_pending_by_session("other") is None


async def test_get_pending_by_session_skips_resolved():
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("p1", session_id="s"))
    await svc.resolve_request("p1", ApprovalDecision.APPROVED)
    _seed_pending(svc, _make_pending("p2", session_id="s"))
    found = await svc.get_pending_by_session("s")
    assert found.request_id == "p2"


async def test_get_all_pending_by_session_excludes_other_sessions():
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("p1", session_id="s1"))
    _seed_pending(svc, _make_pending("p2", session_id="s2"))
    _seed_pending(svc, _make_pending("p3", session_id="s1"))
    found = await svc.get_all_pending_by_session("s1")
    assert {p.request_id for p in found} == {"p1", "p3"}


async def test_list_pending_by_session_sorts_by_created_at():
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("c", session_id="s", created_at=30.0))
    _seed_pending(svc, _make_pending("a", session_id="s", created_at=10.0))
    _seed_pending(svc, _make_pending("b", session_id="s", created_at=20.0))
    listed = await svc.list_pending_by_session("s")
    assert [p.request_id for p in listed] == ["a", "b", "c"]


async def test_get_pending_by_root_session_includes_child_sessions():
    """Cross-session support: a child session's pending must surface under
    the parent root session id."""
    svc = ApprovalService()
    _seed_pending(
        svc,
        _make_pending(
            "child",
            session_id="child-s",
            root_session_id="root",
        ),
    )
    _seed_pending(
        svc,
        _make_pending("parent", session_id="root", root_session_id="root"),
    )
    other = _seed_pending(
        svc,
        _make_pending(
            "other",
            session_id="other-s",
            root_session_id="other-root",
        ),
    )
    found = await svc.get_pending_by_root_session("root")
    assert {p.request_id for p in found} == {"child", "parent"}
    assert other.request_id not in {p.request_id for p in found}


async def test_get_all_pending_by_agent_no_cross_agent_leak():
    """An approval pending for agent-A must not be visible to agent-B —
    the ``--all`` listing is agent-scoped."""
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("p1", agent_id="agent-A"))
    _seed_pending(svc, _make_pending("p2", agent_id="agent-B"))
    _seed_pending(svc, _make_pending("p3", agent_id="agent-A"))
    found = await svc.get_all_pending_by_agent("agent-A")
    assert {p.request_id for p in found} == {"p1", "p3"}
    found_b = await svc.get_all_pending_by_agent("agent-B")
    assert {p.request_id for p in found_b} == {"p2"}
    found_c = await svc.get_all_pending_by_agent("agent-C")
    assert found_c == []


# ---------------------------------------------------------------------------
# wait_for_approval
# ---------------------------------------------------------------------------


async def test_wait_for_approval_unknown_id_raises_value_error():
    svc = ApprovalService()
    with pytest.raises(ValueError):
        await svc.wait_for_approval("nope", timeout_seconds=0.05)


async def test_wait_for_approval_returns_decision_when_resolved():
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("req-w"))
    # Schedule the resolve after the wait starts.
    asyncio.get_event_loop().call_later(
        0.02,
        lambda: svc._pending["req-w"].future.set_result(
            ApprovalDecision.APPROVED,
        ),
    )
    decision = await svc.wait_for_approval("req-w", timeout_seconds=1.0)
    assert decision is ApprovalDecision.APPROVED


async def test_wait_for_approval_timeout_resolves_as_timeout():
    """On timeout the service must self-resolve the record as TIMEOUT and
    remove it from the pending store."""
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("req-t"))
    decision = await svc.wait_for_approval("req-t", timeout_seconds=0.05)
    assert decision is ApprovalDecision.TIMEOUT
    # The pending record was popped by resolve_request.
    assert await svc.get_request("req-t") is None


# ---------------------------------------------------------------------------
# cancellation
# ---------------------------------------------------------------------------


async def test_cancel_stale_pending_for_tool_call_matches_only_same_id():
    svc = ApprovalService()
    p1 = _seed_pending(
        svc,
        _make_pending(
            "p1",
            extra={"tool_call": {"id": "tc-1"}},
        ),
    )
    _seed_pending(
        svc,
        _make_pending(
            "p2",
            extra={"tool_call": {"id": "tc-2"}},
        ),
    )
    _seed_pending(
        svc,
        _make_pending("p3", extra={"tool_call": {"id": None}}),  # no id
    )
    cancelled = await svc.cancel_stale_pending_for_tool_call("s1", "tc-1")
    assert cancelled == 1
    remaining = await svc.get_all_pending_by_session("s1")
    assert {p.request_id for p in remaining} == {"p2", "p3"}
    # Cancelled record popped, marked superseded, future resolved TIMEOUT.
    assert svc._pending.get("p1") is None
    assert p1.status == "superseded"
    assert p1.future.done()
    assert p1.future.result() is ApprovalDecision.TIMEOUT


async def test_cancel_stale_pending_for_tool_call_zero_when_no_match():
    svc = ApprovalService()
    _seed_pending(svc, _make_pending("p1"))
    cancelled = await svc.cancel_stale_pending_for_tool_call("s1", "tc-x")
    assert cancelled == 0


async def test_cancel_all_pending_by_root_session_denies_and_clears():
    """Stopping a task tree auto-denies every pending for that root and
    leaves sibling trees untouched."""
    svc = ApprovalService()
    p1 = _seed_pending(
        svc,
        _make_pending("p1", root_session_id="root-A"),
    )
    p2 = _seed_pending(
        svc,
        _make_pending("p2", root_session_id="root-A"),
    )
    _seed_pending(
        svc,
        _make_pending("p3", root_session_id="root-B"),
    )
    cancelled = await svc.cancel_all_pending_by_root_session("root-A")
    assert cancelled == 2
    # root-A pendings are gone, root-B is untouched.
    assert await svc.get_request("p1") is None
    assert await svc.get_request("p2") is None
    assert await svc.get_request("p3") is not None
    # The cancelled future was resolved DENIED and the status updated.
    assert p1.status == "cancelled"
    assert p1.future.result() is ApprovalDecision.DENIED
    assert p2.status == "cancelled"
    # sibling tree pending still pending
    p3 = await svc.get_request("p3")
    assert p3.status == "pending"


# ---------------------------------------------------------------------------
# GC
# ---------------------------------------------------------------------------


def test_gc_evicts_overflow_oldest_first():
    """When the pending store exceeds ``_GC_MAX_PENDING`` the oldest
    records are evicted first and their futures resolved as TIMEOUT."""
    svc = ApprovalService()
    # Bypass the lock for the test setup — _gc_pending_locked reads the
    # dict directly so seeding via _pending is fine.
    base = time.time()
    for i in range(_GC_MAX_PENDING + 5):
        svc._pending[f"r{i}"] = _make_pending(
            f"r{i}",
            created_at=base + i,
        )
    svc._gc_pending_locked()
    # Overflow reduced to max.
    assert len(svc._pending) == _GC_MAX_PENDING
    # Oldest 5 records gone.
    assert "r0" not in svc._pending
    assert "r4" not in svc._pending
    assert f"r{_GC_MAX_PENDING + 4}" in svc._pending


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_approval_service_returns_singleton(monkeypatch):
    """The module-level accessor returns the same instance per process."""
    import qwenpaw.app.approvals.service as svc_mod

    monkeypatch.setattr(svc_mod, "_approval_service", None)
    first = get_approval_service()
    second = get_approval_service()
    assert first is second
    assert isinstance(first, ApprovalService)
