# -*- coding: utf-8 -*-
"""Regression tests for approval decisions racing with their consumers."""
# pylint: disable=protected-access

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.approvals.models import ApprovalRequestSummary
from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.app.routers import approval as approval_router
from qwenpaw.governance import generalize, tool_adapter
from qwenpaw.governance.policy import ToolCallSpec
from qwenpaw.runtime.commands.control import approval_handler
from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.security.tool_guard.approval import ApprovalDecision


async def _create_pending(service: ApprovalService):
    """Create a console approval without invoking a real tool."""
    return await service.create_pending_summary(
        session_id=f"session-8105",
        root_session_id=f"session-8105",
        owner_agent_id=f"agent-8105",
        user_id=f"user-8105",
        channel=f"console",
        agent_id=f"agent-8105",
        summary=ApprovalRequestSummary(
            source_type=f"tool_guard",
            name=f"Bash",
        ),
    )


@pytest.mark.parametrize(
    f"decision",
    [ApprovalDecision.APPROVED, ApprovalDecision.DENIED],
)
async def test_decision_before_wait_is_preserved(decision):
    """A fast response must reach the consumer after pending removal."""
    service = ApprovalService()
    pending = await _create_pending(service)
    await service.resolve_request(pending.request_id, decision)

    result = await service.wait_for_approval(pending, 1.0)

    assert result is decision
    assert await service.get_request(pending.request_id) is None


@pytest.mark.parametrize(
    (f"decision", f"behavior"),
    [
        (ApprovalDecision.APPROVED, f"allow"),
        (ApprovalDecision.DENIED, f"deny"),
    ],
)
async def test_fast_decision_reaches_governance_tool(
    decision,
    behavior,
    monkeypatch,
):
    """A real service response must preserve the tool's permission result."""
    service = ApprovalService()
    original_create = service.create_pending

    async def _create_then_resolve(**kwargs):
        # pylint: disable-next=missing-kwoa
        pending = await original_create(**kwargs)
        await service.resolve_request(pending.request_id, decision)
        return pending

    monkeypatch.setattr(service, f"create_pending", _create_then_resolve)
    monkeypatch.setattr(
        f"qwenpaw.app.approvals.service._approval_service",
        service,
    )
    monkeypatch.setattr(
        generalize,
        f"generalize_target_for_approval",
        AsyncMock(return_value=None),
    )
    governor = MagicMock()
    governor.add_approved_rule = AsyncMock()

    result = await tool_adapter._ask_user_approval(
        governor=governor,
        tc_spec=ToolCallSpec(
            tool_name=f"Bash",
            target=f"printf QWENPAW_8105",
            agent_id=f"agent-8105",
            session_id=f"session-8105",
        ),
        request_context={f"channel": f"console"},
        source=f"STRICT mode",
    )

    assert result.behavior.value == behavior
    if decision is ApprovalDecision.APPROVED:
        governor.add_approved_rule.assert_awaited_once()
    else:
        governor.add_approved_rule.assert_not_awaited()


async def test_timeout_resolves_shared_future_without_cancelling_it():
    """Every observer must see TIMEOUT instead of CancelledError."""
    service = ApprovalService()
    pending = await _create_pending(service)

    result = await service.wait_for_approval(pending.request_id, 0.01)

    assert result is ApprovalDecision.TIMEOUT
    assert not pending.future.cancelled()
    assert pending.future.result() is ApprovalDecision.TIMEOUT


@pytest.mark.parametrize(f"action", [f"approve", f"deny"])
async def test_action_racing_with_resolution_returns_conflict(
    action,
    monkeypatch,
):
    """Losing a resolution race must not crash or claim success."""
    service = ApprovalService()
    pending = await _create_pending(service)
    original_get = service.get_request

    async def _get_then_resolve(request_id):
        found = await original_get(request_id)
        if found is not None:
            await service.resolve_request(
                request_id,
                ApprovalDecision.DENIED,
            )
        return found

    monkeypatch.setattr(service, f"get_request", _get_then_resolve)
    monkeypatch.setattr(
        approval_router,
        f"get_approval_service",
        lambda: service,
    )
    application = FastAPI()
    application.include_router(approval_router.router)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url=f"http://test",
    ) as client:
        response = await client.post(
            f"/approval/{action}",
            json={
                f"request_id": pending.request_id,
                f"session_id": pending.root_session_id,
            },
        )

    assert response.status_code == 409
    assert pending.future.result() is ApprovalDecision.DENIED


async def test_expired_approval_cannot_be_approved(monkeypatch):
    """A delayed click must not allow execution past the approval deadline."""
    service = ApprovalService()
    pending = await _create_pending(service)
    pending.created_at = time.time() - pending.timeout_seconds - 1
    monkeypatch.setattr(
        approval_router,
        f"get_approval_service",
        lambda: service,
    )
    application = FastAPI()
    application.include_router(approval_router.router)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url=f"http://test",
    ) as client:
        response = await client.post(
            f"/approval/approve",
            json={
                f"request_id": pending.request_id,
                f"session_id": pending.root_session_id,
            },
        )

    assert response.status_code == 409
    assert pending.future.result() is ApprovalDecision.TIMEOUT
    assert await service.get_request(pending.request_id) is None


@pytest.mark.parametrize(f"action", [f"approve", f"deny"])
async def test_expired_approval_command_returns_error(action, monkeypatch):
    """Control commands must handle an expired resolution without crashing."""
    service = ApprovalService()
    pending = await _create_pending(service)
    pending.created_at = time.time() - pending.timeout_seconds - 1
    monkeypatch.setattr(
        approval_handler,
        f"get_approval_service",
        lambda: service,
    )
    context = ControlContext(
        workspace=MagicMock(),
        payload=None,
        channel=None,
        session_id=pending.session_id,
        user_id=pending.user_id,
        agent_id=pending.agent_id,
        args={f"action": action, f"request_id": pending.request_id},
    )

    result = await approval_handler.ApprovalCommandHandler().handle(context)

    assert f"已超时" in result
    assert pending.future.result() is ApprovalDecision.TIMEOUT


async def test_cancelled_waiter_does_not_cancel_another_waiter():
    """Cancelling one UI connection must preserve the shared decision."""
    service = ApprovalService()
    pending = await _create_pending(service)
    first = asyncio.create_task(
        service.wait_for_approval(pending.request_id, 1.0),
    )
    second = asyncio.create_task(
        service.wait_for_approval(pending.request_id, 1.0),
    )
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await service.resolve_request(
        pending.request_id,
        ApprovalDecision.APPROVED,
    )

    assert await second is ApprovalDecision.APPROVED
