# -*- coding: utf-8 -*-
"""请求主体只能由可信认证状态构造。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import Request

from qwenpaw.access.actor import ActorContext, ActorType, actor_from_request
from qwenpaw.identity.models import PlatformRole, UserRecord
from qwenpaw.identity.sessions import AuthenticatedSession, SessionRecord


def _request(*, query: str = "", headers: list[tuple[bytes, bytes]] | None = None):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/test",
            "query_string": query.encode(),
            "headers": headers or [],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def _authenticated(role: PlatformRole) -> AuthenticatedSession:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    user = UserRecord(
        id=uuid4(),
        username="actor-user",
        platform_role=role,
        status="active",
    )
    return AuthenticatedSession(
        user=user,
        session=SessionRecord(
            id=uuid4(),
            user_id=user.id,
            client_info={},
            created_at=now,
            last_seen_at=None,
            access_expires_at=now + timedelta(minutes=15),
            refresh_expires_at=now + timedelta(days=30),
            revoked_at=None,
        ),
    )


def test_multi_user_actor_comes_from_authenticated_session_not_query_user_id() -> None:
    forged_id = uuid4()
    request = _request(query=f"user_id={forged_id}")
    request.state.authenticated_session = _authenticated(PlatformRole.MEMBER)

    actor = actor_from_request(request, multi_user=True)

    assert actor.user_id == request.state.authenticated_session.user.id
    assert actor.user_id != forged_id
    assert actor.actor_type is ActorType.USER
    assert actor.platform_role is PlatformRole.MEMBER
    assert actor.admin_mode is False
    assert actor.request_id


def test_legacy_request_gets_compatibility_admin_actor() -> None:
    request = _request(headers=[(b"x-request-id", b"req-legacy")])
    request.state.user = "legacy-admin"

    actor = actor_from_request(request, multi_user=False)

    assert actor == ActorContext(
        user_id=None,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="req-legacy",
    )


def test_multi_user_request_without_authenticated_session_has_no_actor() -> None:
    request = _request()

    assert actor_from_request(request, multi_user=True) is None
