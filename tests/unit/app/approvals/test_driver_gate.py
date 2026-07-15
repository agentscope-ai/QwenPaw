# -*- coding: utf-8 -*-
"""Unit tests for the driver approval gate.

The gate bridges a Driver policy ``ask`` outcome into the central
``ApprovalService`` Future flow.  These tests exercise the allow path, the
deny path, the missing-session-id guard and the stale-pending eviction
that fires when a Driver replays the same tool call.
"""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,unused-import  # noqa: E501

import asyncio

import pytest

import qwenpaw.app.approvals as approvals_pkg
from qwenpaw.app.approvals.driver_gate import (
    QwenPawDriverApprovalGate,
)
from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
from qwenpaw.drivers.errors import (
    ApprovalRequiredError,
    DriverPermissionDeniedError,
)
from qwenpaw.drivers.policy_types import PolicyTarget
from qwenpaw.drivers.policy import DriverInvocationContext
from qwenpaw.security.tool_guard.approval import ApprovalDecision

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> ApprovalService:
    """Patch ``get_approval_service`` to return a fresh non-singleton
    instance for each test so pendings never leak across cases."""
    fresh = ApprovalService()

    def _factory() -> ApprovalService:
        return fresh

    monkeypatch.setattr(approvals_pkg, "get_approval_service", _factory)
    return fresh


def _ctx(
    *,
    session_id: str = "s1",
    root_session_id: str = "s1",
    agent_id: str = "agent-A",
    root_agent_id: str = "agent-A",
    user_id: str = "u1",
    channel: str = "console",
    tool_call_id: str = "",
    target_kind: str = "*",
    target_name: str = "",
    driver_name: str = "Bash",
    protocol: str = "http",
    operation: str = "invoke",
    subject: str = "user:u1",
) -> DriverInvocationContext:
    return DriverInvocationContext(
        subject=subject,
        driver_name=driver_name,
        protocol=protocol,
        operation=operation,
        target=PolicyTarget(kind=target_kind, name=target_name),
        request_context={
            "session_id": session_id,
            "root_session_id": root_session_id,
            "agent_id": agent_id,
            "root_agent_id": root_agent_id,
            "user_id": user_id,
            "channel": channel,
            "tool_call_id": tool_call_id,
        },
    )


# ---------------------------------------------------------------------------
# Allow / deny paths
# ---------------------------------------------------------------------------


async def test_request_approval_allow_path_resolves_and_returns(
    svc: ApprovalService,
):
    """When the user approves, the gate returns normally and the pending
    record is removed from the store."""
    gate = QwenPawDriverApprovalGate()
    ctx = _ctx(tool_call_id="tc-1")

    # Approve from another task as soon as the pending exists.
    async def _approver() -> None:
        # Spin until the pending has been registered.
        for _ in range(100):
            await asyncio.sleep(0)
            if svc._pending:
                break
        await svc.resolve_request(
            next(iter(svc._pending)),
            ApprovalDecision.APPROVED,
        )

    asyncio.create_task(_approver())
    await gate.request_approval(ctx)

    # After approval, the pending store must be drained.
    assert svc._pending == {}


async def test_request_approval_deny_path_raises_permission_denied(
    svc: ApprovalService,
):
    gate = QwenPawDriverApprovalGate()
    ctx = _ctx(tool_call_id="tc-2")

    async def _denier() -> None:
        for _ in range(100):
            await asyncio.sleep(0)
            if svc._pending:
                break
        await svc.resolve_request(
            next(iter(svc._pending)),
            ApprovalDecision.DENIED,
        )

    asyncio.create_task(_denier())
    with pytest.raises(DriverPermissionDeniedError) as exc:
        await gate.request_approval(ctx)
    assert "User approval decision was denied" in exc.value.reason


async def test_request_approval_missing_session_id_raises_approval_required(
    svc: ApprovalService,
):
    """Without a session_id the gate cannot route the pending — it must
    fail fast with ApprovalRequiredError and never touch the service."""
    gate = QwenPawDriverApprovalGate()
    ctx = _ctx(session_id="")
    with pytest.raises(ApprovalRequiredError):
        await gate.request_approval(ctx)
    assert svc._pending == {}


async def test_request_approval_stale_pending_cancelled_before_new_created(
    svc: ApprovalService,
):
    """A replayed Driver tool call must cancel the prior pending for the
    same ``tool_call_id`` before opening a fresh one, so orphaned records
    don't accumulate."""
    gate = QwenPawDriverApprovalGate()
    ctx = _ctx(tool_call_id="tc-3")

    # Pre-seed an orphan pending for the same tool_call_id.
    orphan = PendingApproval(
        request_id="orphan",
        session_id="s1",
        root_session_id="s1",
        owner_agent_id="agent-A",
        user_id="u1",
        channel="console",
        agent_id="agent-A",
        tool_name="driver:http:Bash",
        created_at=0.0,
        future=asyncio.get_event_loop().create_future(),
        extra={
            "tool_call": {
                "id": "tc-3",
                "name": "driver:http:Bash",
                "input": {},
            },
        },
    )
    svc._pending["orphan"] = orphan

    # Approve the freshly-created pending as soon as it appears.
    async def _approver() -> None:
        for _ in range(100):
            await asyncio.sleep(0)
            # The orphan was cancelled, so the only entry is the new one.
            if "orphan" not in svc._pending and svc._pending:
                break
        await svc.resolve_request(
            next(iter(svc._pending)),
            ApprovalDecision.APPROVED,
        )

    asyncio.create_task(_approver())
    await gate.request_approval(ctx)

    # Orphan was evicted; new pending was approved and popped.
    assert "orphan" not in svc._pending
    assert orphan.status == "superseded"


async def test_request_approval_with_tool_target_uses_target_name_in_summary(
    svc: ApprovalService,
):
    """When the policy target is a tool, the result_summary must refer to
    the tool name and source rather than the bare driver label."""
    gate = QwenPawDriverApprovalGate()
    ctx = _ctx(
        tool_call_id="tc-4",
        target_kind="tool",
        target_name="run_shell",
    )

    async def _approver() -> None:
        for _ in range(100):
            await asyncio.sleep(0)
            if svc._pending:
                break
        pending = next(iter(svc._pending.values()))
        # Sanity: the summary mentions the tool, not just the driver label.
        assert "run_shell" in pending.result_summary
        await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
        )

    asyncio.create_task(_approver())
    await gate.request_approval(ctx)
