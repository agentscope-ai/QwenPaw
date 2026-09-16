# -*- coding: utf-8 -*-
"""多用户会话必须使用可信身份并拒绝跨用户资源访问。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.chats import api as chats_api
from qwenpaw.app.chats.access import (
    ChatAccessDeniedError,
    require_chat_owner,
    resolve_chat_user_id,
)
from qwenpaw.app.chats.models import ChatSpec, ChatUpdate
from qwenpaw.app.routers import console as console_router
from qwenpaw.identity.models import PlatformRole


def _actor(user_id=None) -> ActorContext:
    return ActorContext(
        user_id=user_id or uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="req-chat-isolation",
    )


def _request(actor: ActorContext) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/agents/public-agent/chats",
            "headers": [],
            "query_string": b"",
            "app": FastAPI(),
        }
    )
    request.state.actor = actor
    return request


def _legacy_owner_request(actor: ActorContext) -> Request:
    request = _request(actor)
    request.state.agent_access = SimpleNamespace(
        role="owner",
    )
    return request


def test_multi_user_ignores_client_supplied_chat_user_id() -> None:
    actor = _actor()

    assert (
        resolve_chat_user_id(
            actor=actor,
            requested_user_id="default",
            multi_user=True,
        )
        == str(actor.user_id)
    )


def test_legacy_preserves_original_chat_user_id() -> None:
    actor = _actor()

    assert (
        resolve_chat_user_id(
            actor=actor,
            requested_user_id="legacy-user",
            multi_user=False,
        )
        == "legacy-user"
    )


def test_multi_user_rejects_chat_owned_by_another_user() -> None:
    actor = _actor()
    foreign_chat = SimpleNamespace(user_id=str(uuid4()))

    with pytest.raises(ChatAccessDeniedError):
        require_chat_owner(
            actor=actor,
            chat=foreign_chat,
            multi_user=True,
        )


def test_multi_user_allows_chat_owned_by_authenticated_user() -> None:
    actor = _actor()
    owned_chat = SimpleNamespace(user_id=str(actor.user_id))

    assert (
        require_chat_owner(
            actor=actor,
            chat=owned_chat,
            multi_user=True,
        )
        is owned_chat
    )


def test_legacy_default_chat_requires_explicit_compatibility_scope() -> None:
    actor = _actor()
    legacy_chat = SimpleNamespace(user_id="default")

    with pytest.raises(ChatAccessDeniedError):
        require_chat_owner(
            actor=actor,
            chat=legacy_chat,
            multi_user=True,
        )

    assert (
        require_chat_owner(
            actor=actor,
            chat=legacy_chat,
            multi_user=True,
            legacy_user_ids=frozenset({"default"}),
        )
        is legacy_chat
    )


@pytest.mark.asyncio
async def test_create_chat_overrides_forged_user_id(monkeypatch) -> None:
    actor = _actor()
    manager = SimpleNamespace(create_chat=AsyncMock(side_effect=lambda chat: chat))
    monkeypatch.setattr(chats_api, "is_multi_user_enabled", lambda: True)

    created = await chats_api.create_chat(
        payload=ChatSpec(
            name="private conversation",
            session_id="client-session",
            user_id="default",
            channel="console",
        ),
        request=_request(actor),
        mgr=manager,
    )

    assert created.user_id == str(actor.user_id)
    assert manager.create_chat.await_args.args[0].user_id == str(actor.user_id)


@pytest.mark.asyncio
async def test_list_chats_ignores_forged_user_filter(monkeypatch) -> None:
    actor = _actor()
    manager = SimpleNamespace(list_accessible_chats=AsyncMock(return_value=[]))
    workspace = SimpleNamespace(task_tracker=SimpleNamespace(get_status=AsyncMock()))
    monkeypatch.setattr(chats_api, "is_multi_user_enabled", lambda: True)

    await chats_api.list_chats(
        request=_request(actor),
        user_id=str(uuid4()),
        channel=None,
        archived=None,
        scope="all",
        mgr=manager,
        workspace=workspace,
    )

    assert manager.list_accessible_chats.await_args.kwargs["user_id"] == actor.user_id


@pytest.mark.asyncio
async def test_legacy_list_chats_preserves_unfiltered_query(monkeypatch) -> None:
    actor = _actor()
    manager = SimpleNamespace(list_chats=AsyncMock(return_value=[]))
    workspace = SimpleNamespace(task_tracker=SimpleNamespace(get_status=AsyncMock()))
    monkeypatch.setattr(chats_api, "is_multi_user_enabled", lambda: False)

    await chats_api.list_chats(
        request=_request(actor),
        user_id=None,
        channel=None,
        archived=None,
        scope="all",
        mgr=manager,
        workspace=workspace,
    )

    assert manager.list_chats.await_args.kwargs["user_id"] is None


@pytest.mark.asyncio
async def test_admin_list_uses_only_postgres_authorized_chats(monkeypatch) -> None:
    member_actor = _actor()
    actor = ActorContext(
        user_id=member_actor.user_id,
        actor_type=member_actor.actor_type,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id=member_actor.request_id,
    )
    authorized_chat = ChatSpec(
        session_id="authorized-session",
        user_id=str(actor.user_id),
        channel="console",
    )
    access = SimpleNamespace(
        access_role="owner",
        read_only=False,
        shared_by_username=None,
    )
    manager = SimpleNamespace(
        list_accessible_chats=AsyncMock(
            return_value=[SimpleNamespace(chat=authorized_chat, access=access)]
        ),
    )
    workspace = SimpleNamespace(
        task_tracker=SimpleNamespace(get_status=AsyncMock(return_value="idle")),
    )
    monkeypatch.setattr(chats_api, "is_multi_user_enabled", lambda: True)

    chats = await chats_api.list_chats(
        request=_legacy_owner_request(actor),
        user_id=None,
        channel=None,
        archived=None,
        scope="all",
        mgr=manager,
        workspace=workspace,
    )

    assert [chat.id for chat in chats] == [authorized_chat.id]
    manager.list_accessible_chats.assert_awaited_once_with(
        user_id=actor.user_id,
        scope="all",
        channel=None,
        archived=None,
    )


@pytest.mark.asyncio
async def test_member_list_does_not_fall_back_to_legacy_default_chats(monkeypatch) -> None:
    actor = _actor()
    manager = SimpleNamespace(list_accessible_chats=AsyncMock(return_value=[]))
    workspace = SimpleNamespace(task_tracker=SimpleNamespace(get_status=AsyncMock()))
    monkeypatch.setattr(chats_api, "is_multi_user_enabled", lambda: True)

    await chats_api.list_chats(
        request=_legacy_owner_request(actor),
        user_id=None,
        channel=None,
        archived=None,
        scope="all",
        mgr=manager,
        workspace=workspace,
    )

    manager.list_accessible_chats.assert_awaited_once_with(
        user_id=actor.user_id,
        scope="all",
        channel=None,
        archived=None,
    )


@pytest.mark.asyncio
async def test_update_chat_hides_foreign_chat_and_does_not_mutate(monkeypatch) -> None:
    actor = _actor()
    foreign_chat = ChatSpec(
        session_id="foreign-session",
        user_id=str(uuid4()),
        channel="console",
    )
    bound_repository = SimpleNamespace(
        get_conversation_for_user=AsyncMock(return_value=None),
    )
    conversation_repository = SimpleNamespace(
        with_user=lambda _user_id: bound_repository,
    )
    manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=foreign_chat),
        patch_chat=AsyncMock(),
        conversation_repository=conversation_repository,
    )
    monkeypatch.setattr(chats_api, "is_multi_user_enabled", lambda: True)

    with pytest.raises(chats_api.HTTPException) as exc_info:
        await chats_api.update_chat(
            chat_id=foreign_chat.id,
            spec=ChatUpdate(name="forged rename"),
            request=_request(actor),
            mgr=manager,
            workspace=SimpleNamespace(agent_id="public-agent"),
        )

    assert exc_info.value.status_code == 404
    manager.patch_chat.assert_not_awaited()


def test_console_payload_uses_authenticated_user_for_session_identity(
    monkeypatch,
) -> None:
    actor = _actor()
    payload = {
        "sender_id": "default",
        "meta": {"user_id": "default", "session_id": "client-session"},
    }
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)

    console_router._apply_trusted_chat_identity(_request(actor), payload)

    assert payload["sender_id"] == str(actor.user_id)
    assert payload["meta"]["user_id"] == str(actor.user_id)


def test_console_payload_overrides_forged_background_identity_context(
    monkeypatch,
) -> None:
    """后台执行上下文中的用户、审批人与主体快照必须来自认证状态。"""
    actor = _actor()
    payload = {
        "sender_id": "forged-user",
        "meta": {
            "user_id": "forged-user",
            "session_id": "client-session",
            "request_context": {
                "user_id": "forged-user",
                "approval_user_id": "forged-approver",
                "actor_context": {"user_id": "forged-actor"},
            },
        },
    }
    monkeypatch.setattr(console_router, "is_multi_user_enabled", lambda: True)

    console_router._apply_trusted_chat_identity(_request(actor), payload)

    request_context = payload["meta"]["request_context"]
    assert request_context["user_id"] == str(actor.user_id)
    assert request_context["approval_user_id"] == str(actor.user_id)
    assert request_context["actor_context"] == {
        "user_id": str(actor.user_id),
        "actor_type": actor.actor_type.value,
        "platform_role": actor.platform_role.value,
        "admin_mode": actor.admin_mode,
        "request_id": actor.request_id,
    }
