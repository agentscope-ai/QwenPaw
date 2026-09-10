# -*- coding: utf-8 -*-
"""Tests for approval-gated side-effecting ReMe slash actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.runtime.builtin_commands import _request_reme_action_approval
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
