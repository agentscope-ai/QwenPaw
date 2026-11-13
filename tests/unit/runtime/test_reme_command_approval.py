# -*- coding: utf-8 -*-
"""Tests for approval-gated side-effecting ReMe slash actions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.approvals.models import ApprovalRequestSummary
from qwenpaw.app.approvals.service import (
    ApprovalIdentityPolicy,
    ApprovalService,
)
from qwenpaw.runtime.builtin_commands import _request_reme_action_approval
from qwenpaw.runtime.commands.control.approval_handler import (
    ApprovalCommandHandler,
)
from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.security.tool_guard.approval import ApprovalDecision


@pytest.mark.asyncio
async def test_reme_action_uses_shared_approval_service(monkeypatch) -> None:
    service = SimpleNamespace(
        create_pending_summary=AsyncMock(
            return_value=SimpleNamespace(request_id="approval-1"),
        ),
        wait_for_approval=AsyncMock(
            return_value=ApprovalDecision.APPROVED,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: service,
    )
    ctx = SimpleNamespace(
        request=SimpleNamespace(
            user_id="user-1",
            channel="console",
            metadata={"client": "console"},
        ),
        session_id="session-1",
        root_session_id="root-session-1",
        agent_id="agent-1",
        root_agent_id="agent-1",
        workspace=SimpleNamespace(channel_manager=None),
    )

    approved = await _request_reme_action_approval(
        ctx,
        "daily_paper",
        {"topics": "agents"},
    )

    assert approved is True
    create_kwargs = service.create_pending_summary.await_args.kwargs
    assert create_kwargs["session_id"] == "session-1"
    assert create_kwargs["user_id"] == "user-1"
    assert create_kwargs["agent_id"] == "agent-1"
    assert create_kwargs["summary"].source_type == "reme_action"
    assert (
        create_kwargs["identity_policy"]
        is ApprovalIdentityPolicy.EXACT_REQUESTER
    )
    service.wait_for_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_reme_action_denies_when_approval_is_rejected(
    monkeypatch,
) -> None:
    service = SimpleNamespace(
        create_pending_summary=AsyncMock(
            return_value=SimpleNamespace(request_id="approval-2"),
        ),
        wait_for_approval=AsyncMock(
            return_value=ApprovalDecision.DENIED,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: service,
    )
    ctx = SimpleNamespace(
        request=SimpleNamespace(user_id="user-1", channel="console"),
        session_id="session-1",
        root_session_id="session-1",
        agent_id="agent-1",
        root_agent_id="agent-1",
        workspace=SimpleNamespace(channel_manager=None),
    )

    approved = await _request_reme_action_approval(
        ctx,
        "auto_dream",
        {},
    )

    assert approved is False


@pytest.mark.asyncio
async def test_other_requester_cannot_approve_reme_action(monkeypatch) -> None:
    service = ApprovalService()
    pending = await service.create_pending_summary(
        session_id="session-a",
        root_session_id="session-a",
        owner_agent_id="agent-1",
        user_id="user-a",
        channel="channel-a",
        agent_id="agent-1",
        summary=ApprovalRequestSummary(
            source_type="reme_action",
            name="reme:auto_fin",
        ),
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.commands.control.approval_handler."
        "get_approval_service",
        lambda: service,
    )
    context = ControlContext(
        workspace=SimpleNamespace(),
        payload=SimpleNamespace(
            channel="channel-b",
            root_session_id="session-b",
        ),
        channel=None,
        session_id="session-b",
        user_id="user-b",
        agent_id="agent-1",
        args={"action": "approve", "request_id": pending.request_id},
    )

    response = await ApprovalCommandHandler().handle(context)

    assert "权限不足" in response
    assert await service.get_request(pending.request_id) is pending
    assert not pending.future.done()

    context.args = {"action": "list", "all": True}
    response = await ApprovalCommandHandler().handle(context)
    assert "无待审批工具" in response


@pytest.mark.asyncio
async def test_original_requester_can_approve_reme_action(monkeypatch) -> None:
    service = ApprovalService()
    pending = await service.create_pending_summary(
        session_id="session-a",
        root_session_id="root-a",
        owner_agent_id="agent-1",
        user_id="user-a",
        channel="channel-a",
        agent_id="agent-1",
        summary=ApprovalRequestSummary(
            source_type="reme_action",
            name="reme:auto_fin",
        ),
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.commands.control.approval_handler."
        "get_approval_service",
        lambda: service,
    )
    context = ControlContext(
        workspace=SimpleNamespace(),
        payload=SimpleNamespace(
            channel="channel-a",
            root_session_id="root-a",
        ),
        channel=None,
        session_id="session-a",
        user_id="user-a",
        agent_id="agent-1",
        args={"action": "approve", "request_id": pending.request_id},
    )

    response = await ApprovalCommandHandler().handle(context)

    assert "工具已批准" in response
    assert pending.future.result() is ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_cancelled_reme_wait_removes_pending_approval(
    monkeypatch,
) -> None:
    pending = SimpleNamespace(request_id="approval-cancelled")
    service = SimpleNamespace(
        create_pending_summary=AsyncMock(return_value=pending),
        wait_for_approval=AsyncMock(side_effect=asyncio.CancelledError),
        resolve_request=AsyncMock(return_value=pending),
    )
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: service,
    )
    ctx = SimpleNamespace(
        request=SimpleNamespace(user_id="user-1", channel="console"),
        session_id="session-1",
        root_session_id="session-1",
        agent_id="agent-1",
        root_agent_id="agent-1",
        workspace=SimpleNamespace(channel_manager=None),
    )

    with pytest.raises(asyncio.CancelledError):
        await _request_reme_action_approval(ctx, "auto_dream", {})

    resolve_kwargs = service.resolve_request.await_args.kwargs
    assert resolve_kwargs["actor"].user_id == "user-1"
    assert resolve_kwargs["actor"].session_id == "session-1"
