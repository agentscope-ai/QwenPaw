# -*- coding: utf-8 -*-
"""Task 5.3-D 共享会话审批写隔离契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.repo import ConversationAccessRecord, ConversationRecord
from qwenpaw.app.routers.approval import ApprovalActionRequest, post_approval_approve
from qwenpaw.identity.models import PlatformRole


@pytest.mark.asyncio
async def test_viewer_cannot_approve_shared_conversation(monkeypatch) -> None:
    owner_id = uuid4()
    viewer_id = uuid4()
    conversation_id = uuid4()
    now = datetime.now(UTC)
    conversation = ConversationRecord(
        id=conversation_id,
        agent_id=agent_database_id("agent-a"),
        owner_user_id=owner_id,
        title="Shared chat",
        status="active",
        created_at=now,
        updated_at=now,
    )

    class Repository:
        def with_user(self, _user_id):
            return self

        async def get_conversation_for_user(self, **_kwargs):
            return ConversationAccessRecord(
                conversation=conversation,
                access_role="viewer",
            )

    class ApprovalService:
        resolved = False

        async def get_request(self, _request_id):
            return SimpleNamespace(
                root_session_id="console:owner",
                channel="console",
                user_id=str(owner_id),
            )

        async def resolve_request(self, *_args, **_kwargs):
            self.resolved = True
            return SimpleNamespace(tool_name="shell")

    service = ApprovalService()
    class ChatManager:
        conversation_repository = Repository()

        async def get_chat_id_by_session(self, **_kwargs):
            return str(conversation_id)

    workspace = SimpleNamespace(agent_id="agent-a", chat_manager=ChatManager())
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=viewer_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="approval-shared-write-test",
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_approval_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_agent_for_request",
        lambda _request: _async_value(workspace),
        raising=False,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.is_multi_user_enabled",
        lambda: True,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await post_approval_approve(
            request,
            ApprovalActionRequest(
                request_id="approval-1",
                session_id="console:owner",
                conversation_id=str(conversation_id),
            ),
        )

    assert exc_info.value.status_code == 404
    assert service.resolved is False


@pytest.mark.asyncio
async def test_owner_approval_uses_bound_conversation_id_before_legacy_session_lookup(
    monkeypatch,
) -> None:
    owner_id = uuid4()
    conversation_id = uuid4()
    now = datetime.now(UTC)
    conversation = ConversationRecord(
        id=conversation_id,
        agent_id=agent_database_id("agent-a"),
        owner_user_id=owner_id,
        title="Legacy owned chat",
        status="active",
        created_at=now,
        updated_at=now,
    )

    class Repository:
        def with_user(self, _user_id):
            return self

        async def get_conversation_for_user(self, **_kwargs):
            return ConversationAccessRecord(
                conversation=conversation,
                access_role="owner",
            )

    class ApprovalService:
        async def get_request(self, _request_id):
            return SimpleNamespace(
                root_session_id="legacy-session",
                channel="console",
                user_id="default",
                approval_user_id=str(owner_id),
                extra={"conversation_id": str(conversation_id)},
            )

        async def resolve_request(self, *_args, **_kwargs):
            return SimpleNamespace(tool_name="Read")

    class ChatManager:
        conversation_repository = Repository()

        async def get_chat_id_by_session(self, **_kwargs):
            pytest.fail("bound conversation_id must be authoritative")

    workspace = SimpleNamespace(
        agent_id="agent-a",
        chat_manager=ChatManager(),
    )
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=owner_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="approval-legacy-owner-test",
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_approval_service",
        lambda: ApprovalService(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.get_agent_for_request",
        lambda _request: _async_value(workspace),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.approval.is_multi_user_enabled",
        lambda: True,
    )

    result = await post_approval_approve(
        request,
        ApprovalActionRequest(
            request_id="approval-owner",
            session_id="legacy-session",
            conversation_id=str(conversation_id),
        ),
    )

    assert result.success is True


async def _async_value(value):
    return value
