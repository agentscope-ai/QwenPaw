# -*- coding: utf-8 -*-
"""Task 10.3 私人通知、Trace 与审批权限契约。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import console as console_router
from qwenpaw.app.approvals.service import ApprovalService, PendingApproval
from qwenpaw.app.routers.approval import (
    ApprovalActionRequest,
    post_approval_approve,
)
from qwenpaw.identity.models import PlatformRole
import asyncio
import time


def _request(user_id, role=PlatformRole.MEMBER) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="task-10-3",
    )
    return request


@pytest.mark.asyncio
async def test_batch_delete_binds_current_user(monkeypatch) -> None:
    actor_id = uuid4()
    captured: dict[str, object] = {}

    async def delete_events(event_ids, *, recipient_user_id=None):
        captured.update(event_ids=event_ids, recipient_user_id=recipient_user_id)
        return 1

    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.app.inbox_store.delete_events", delete_events)

    result = await console_router.delete_inbox_events(
        console_router.DeleteInboxEventsRequest(event_ids=["mine", "other"]),
        _request(actor_id),
    )

    assert result == {"deleted": 1}
    assert captured == {
        "event_ids": ["mine", "other"],
        "recipient_user_id": str(actor_id),
    }


@pytest.mark.asyncio
async def test_trace_requires_current_users_notification_even_for_admin(
    monkeypatch,
) -> None:
    actor_id = uuid4()
    captured: dict[str, object] = {}

    async def has_run_reference(run_id, *, recipient_user_id=None):
        captured.update(run_id=run_id, recipient_user_id=recipient_user_id)
        return False

    async def fail_if_read(_run_id):
        raise AssertionError("unauthorized trace must not be read")

    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.app.inbox_store.has_run_reference",
        has_run_reference,
    )
    monkeypatch.setattr("qwenpaw.app.inbox_trace_store.get_trace", fail_if_read)

    with pytest.raises(HTTPException) as exc_info:
        await console_router.get_inbox_trace(
            "other-run",
            _request(actor_id, PlatformRole.ADMIN),
        )

    assert exc_info.value.status_code == 404
    assert captured == {
        "run_id": "other-run",
        "recipient_user_id": str(actor_id),
    }


@pytest.mark.asyncio
async def test_multi_user_delete_never_deletes_shared_trace(monkeypatch) -> None:
    actor_id = uuid4()
    trace_deleted = False

    async def delete_event(_event_id, *, recipient_user_id=None):
        assert recipient_user_id == str(actor_id)
        return True, "shared-run", False

    async def delete_trace(_run_id):
        nonlocal trace_deleted
        trace_deleted = True
        return True

    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("qwenpaw.app.inbox_store.delete_event", delete_event)
    monkeypatch.setattr("qwenpaw.app.inbox_trace_store.delete_trace", delete_trace)

    result = await console_router.delete_inbox_event("mine", _request(actor_id))

    assert result["deleted"] is True
    assert result["trace_deleted"] is False
    assert trace_deleted is False


@pytest.mark.asyncio
async def test_admin_cannot_approve_another_users_side_effect(monkeypatch) -> None:
    approval_user_id = uuid4()
    admin_id = uuid4()
    service = ApprovalService()
    pending = PendingApproval(
        request_id=str(uuid4()),
        session_id=f"console:{approval_user_id}",
        root_session_id=f"console:{approval_user_id}",
        owner_agent_id="agent-a",
        user_id=str(approval_user_id),
        channel="console",
        agent_id="agent-a",
        tool_name="execute_shell_command",
        created_at=time.time(),
        future=asyncio.get_running_loop().create_future(),
        approval_user_id=str(approval_user_id),
    )
    service._pending[pending.request_id] = pending  # pylint: disable=protected-access
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.is_multi_user_enabled",
        lambda: True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await post_approval_approve(
            _request(admin_id, PlatformRole.ADMIN),
            ApprovalActionRequest(
                request_id=pending.request_id,
                session_id=pending.root_session_id,
            ),
        )

    assert exc_info.value.status_code == 404
    assert pending.request_id in service._pending  # pylint: disable=protected-access
