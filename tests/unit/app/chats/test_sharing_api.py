# -*- coding: utf-8 -*-
"""Task 5.3-B 会话分享 API 权限契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.api import (
    AddConversationMemberRequest,
    _require_readable_chat,
    add_conversation_member,
    get_chat,
    list_conversation_share_candidates,
    update_chat,
)
from qwenpaw.app.chats.models import ChatSpec, ChatUpdate
from qwenpaw.app.chats.repo import (
    ConversationAccessRecord,
    ConversationRecord,
    ShareCandidate,
)
from qwenpaw.identity.models import PlatformRole


def _request(user_id: UUID) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="sharing-test",
    )
    return request


class _Repository:
    def __init__(self, conversation: ConversationRecord) -> None:
        self.conversation = conversation
        self.added: list[tuple[UUID, UUID, UUID]] = []

    def with_user(self, _user_id: UUID):
        return self

    async def get_conversation(self, _conversation_id: UUID):
        return self.conversation

    async def get_conversation_for_user(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
    ):
        if conversation_id != self.conversation.id:
            return None
        return ConversationAccessRecord(
            conversation=self.conversation,
            access_role=(
                "owner" if user_id == self.conversation.owner_user_id else "viewer"
            ),
            shared_by_username=(
                None if user_id == self.conversation.owner_user_id else "owner-user"
            ),
        )

    async def list_share_candidates(self, *, conversation_id: UUID, owner_user_id: UUID):
        assert conversation_id == self.conversation.id
        assert owner_user_id == self.conversation.owner_user_id
        return [
            ShareCandidate(
                user_id=uuid4(),
                username="eligible-user",
                platform_role="member",
            )
        ]

    async def add_viewer(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        granted_by: UUID,
    ):
        self.added.append((conversation_id, user_id, granted_by))
        return SimpleNamespace(
            conversation_id=conversation_id,
            user_id=user_id,
            username="eligible-user",
            role="viewer",
            granted_by=granted_by,
            created_at=datetime.now(UTC),
        )


class _Manager:
    def __init__(
        self,
        repository: _Repository,
        *,
        chat_user_id: UUID | None = None,
    ) -> None:
        self.conversation_repository = repository
        self.chat_user_id = chat_user_id
        self.patched: list[tuple[str, ChatUpdate]] = []

    async def get_chat(self, chat_id: str):
        if chat_id != str(self.conversation_repository.conversation.id):
            return None
        return ChatSpec(
            id=chat_id,
            session_id="console:owner",
            user_id=str(
                self.chat_user_id
                or self.conversation_repository.conversation.owner_user_id
            ),
        )

    async def patch_chat(self, chat_id: str, spec: ChatUpdate):
        self.patched.append((chat_id, spec))
        return await self.get_chat(chat_id)


def _conversation(*, owner_user_id: UUID, agent_key: str) -> ConversationRecord:
    now = datetime.now(UTC)
    return ConversationRecord(
        id=uuid4(),
        agent_id=agent_database_id(agent_key),
        owner_user_id=owner_user_id,
        title="Owner chat",
        status="active",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_owner_can_list_candidates_and_add_viewer() -> None:
    owner_id = uuid4()
    conversation = _conversation(owner_user_id=owner_id, agent_key="agent-a")
    repository = _Repository(conversation)
    manager = _Manager(repository)
    workspace = SimpleNamespace(agent_id="agent-a")

    candidates = await list_conversation_share_candidates(
        str(conversation.id),
        _request(owner_id),
        mgr=manager,
        workspace=workspace,
    )
    target_id = candidates[0].user_id
    member = await add_conversation_member(
        str(conversation.id),
        AddConversationMemberRequest(user_id=target_id),
        _request(owner_id),
        mgr=manager,
        workspace=workspace,
    )

    assert member.user_id == target_id
    assert repository.added == [(conversation.id, target_id, owner_id)]


@pytest.mark.asyncio
async def test_non_owner_cannot_discover_share_management() -> None:
    owner_id = uuid4()
    viewer_id = uuid4()
    conversation = _conversation(owner_user_id=owner_id, agent_key="agent-a")
    manager = _Manager(_Repository(conversation))

    with pytest.raises(HTTPException) as exc_info:
        await list_conversation_share_candidates(
            str(conversation.id),
            _request(viewer_id),
            mgr=manager,
            workspace=SimpleNamespace(agent_id="agent-a"),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_from_another_agent_is_hidden() -> None:
    owner_id = uuid4()
    conversation = _conversation(owner_user_id=owner_id, agent_key="agent-b")
    manager = _Manager(_Repository(conversation))

    with pytest.raises(HTTPException) as exc_info:
        await list_conversation_share_candidates(
            str(conversation.id),
            _request(owner_id),
            mgr=manager,
            workspace=SimpleNamespace(agent_id="agent-a"),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_shared_viewer_can_resolve_read_only_chat_history() -> None:
    owner_id = uuid4()
    viewer_id = uuid4()
    conversation = _conversation(owner_user_id=owner_id, agent_key="agent-a")
    manager = _Manager(_Repository(conversation))

    chat, access = await _require_readable_chat(
        _request(viewer_id),
        manager,
        SimpleNamespace(agent_id="agent-a"),
        str(conversation.id),
    )

    assert chat.id == str(conversation.id)
    assert access.access_role == "viewer"
    assert access.read_only is True
    assert access.shared_by_username == "owner-user"


@pytest.mark.asyncio
async def test_shared_history_response_exposes_viewer_metadata(monkeypatch) -> None:
    owner_id = uuid4()
    viewer_id = uuid4()
    conversation = _conversation(owner_user_id=owner_id, agent_key="agent-a")
    manager = _Manager(_Repository(conversation))

    class _Session:
        async def get_session_state_dict(self, *_args):
            return {}

    class _Tracker:
        async def get_status(self, _chat_id: str):
            return "idle"

    monkeypatch.setattr(
        "qwenpaw.app.chats.api.is_multi_user_enabled",
        lambda: True,
    )
    history = await get_chat(
        str(conversation.id),
        _request(viewer_id),
        mgr=manager,
        session=_Session(),
        workspace=SimpleNamespace(
            agent_id="agent-a",
            task_tracker=_Tracker(),
            config=SimpleNamespace(backend="qwenpaw"),
        ),
    )

    assert history.messages == []
    assert history.access_role == "viewer"
    assert history.read_only is True
    assert history.shared_by == "owner-user"


@pytest.mark.asyncio
async def test_viewer_cannot_update_chat_even_when_legacy_spec_claims_ownership(
    monkeypatch,
) -> None:
    """写权限必须来自 PostgreSQL 会话角色，不能信任旧 JSON user_id。"""
    owner_id = uuid4()
    viewer_id = uuid4()
    conversation = _conversation(owner_user_id=owner_id, agent_key="agent-a")
    manager = _Manager(
        _Repository(conversation),
        chat_user_id=viewer_id,
    )
    monkeypatch.setattr(
        "qwenpaw.app.chats.api.is_multi_user_enabled",
        lambda: True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await update_chat(
            str(conversation.id),
            ChatUpdate(name="tampered"),
            _request(viewer_id),
            mgr=manager,
            workspace=SimpleNamespace(agent_id="agent-a"),
        )

    assert exc_info.value.status_code == 404
    assert manager.patched == []
