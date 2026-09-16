# -*- coding: utf-8 -*-
"""多用户认证中间件必须验证数据库会话并保留 Legacy 分支。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app import auth
from qwenpaw.identity.models import PlatformRole, UserRecord
from qwenpaw.identity.sessions import AuthenticatedSession, SessionRecord


def authenticated_session() -> AuthenticatedSession:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    user = UserRecord(
        id=uuid4(),
        username="member",
        platform_role=PlatformRole.MEMBER,
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


class FakeSessions:
    def __init__(self, expected_token: str) -> None:
        self.expected_token = expected_token

    async def authenticate_access(self, token: str):
        return authenticated_session() if token == self.expected_token else None


def build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: True, raising=False)
    monkeypatch.setattr(
        auth,
        "get_identity_runtime",
        lambda: SimpleNamespace(sessions=FakeSessions("valid-access")),
        raising=False,
    )
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)

    @app.get("/api/protected")
    async def protected(request: Request):
        identity = request.state.authenticated_session
        actor = request.state.actor
        return {
            "username": identity.user.username,
            "actor_user_id": str(actor.user_id),
            "actor_role": actor.platform_role.value,
        }

    @app.post("/api/auth/refresh")
    async def refresh():
        return {"public": True}

    @app.api_route("/api/mcp/oauth/callback", methods=["GET", "POST"])
    async def mcp_oauth_callback():
        return {"callback": True}

    @app.get("/api/mcp/oauth/callback/extra")
    async def mcp_oauth_callback_extra():
        return {"callback": False}

    return TestClient(app)


def test_multi_user_middleware_accepts_database_access_session(monkeypatch) -> None:
    client = build_client(monkeypatch)
    response = client.get(
        "/api/protected",
        headers={"Authorization": "Bearer valid-access"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "member"
    assert payload["actor_user_id"]
    assert payload["actor_role"] == "member"


def test_multi_user_middleware_rejects_missing_or_invalid_access(monkeypatch) -> None:
    client = build_client(monkeypatch)
    assert client.get("/api/protected").status_code == 401
    assert (
        client.get(
            "/api/protected",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )


def test_refresh_route_remains_public_for_cookie_rotation(monkeypatch) -> None:
    client = build_client(monkeypatch)
    response = client.post("/api/auth/refresh")
    assert response.status_code == 200
    assert response.json() == {"public": True}


def test_only_exact_get_mcp_oauth_callback_is_public(monkeypatch) -> None:
    client = build_client(monkeypatch)

    callback = client.get(
        "/api/mcp/oauth/callback",
        params={"code": "synthetic", "state": "synthetic"},
    )

    assert callback.status_code == 200
    assert callback.json() == {"callback": True}
    assert client.post("/api/mcp/oauth/callback").status_code == 401
    assert client.get("/api/mcp/oauth/callback/extra").status_code == 401
    assert client.get("/api/mcp/oauth/callback-evil").status_code == 401
