# -*- coding: utf-8 -*-
"""多用户登录、刷新 Cookie 与当前用户 API 契约。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.routers import auth as auth_router
from qwenpaw.app.routers import me as me_router
from qwenpaw.identity.models import PlatformRole, UserProfileUpdate, UserRecord
from qwenpaw.identity.service import CurrentPasswordIncorrectError
from qwenpaw.identity.preferences import UserPreferences
from qwenpaw.identity.sessions import (
    AuthenticatedSession,
    IssuedSession,
    SessionRecord,
)

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
ADMIN = UserRecord(
    id=uuid4(),
    username="admin",
    platform_role=PlatformRole.ADMIN,
    status="active",
)
SESSION = SessionRecord(
    id=uuid4(),
    user_id=ADMIN.id,
    client_info={"user_agent": "pytest"},
    created_at=NOW,
    last_seen_at=None,
    access_expires_at=NOW + timedelta(minutes=15),
    refresh_expires_at=NOW + timedelta(days=30),
    revoked_at=None,
)


def issued(access: str = "access-one", refresh: str = "refresh-one"):
    return IssuedSession(
        access_token=access,
        refresh_token=refresh,
        access_expires_at=SESSION.access_expires_at,
        refresh_expires_at=SESSION.refresh_expires_at,
        authenticated=AuthenticatedSession(user=ADMIN, session=SESSION),
    )


class FakeUsers:
    def __init__(self) -> None:
        self.has_users_value = True

    async def has_users(self) -> bool:
        return self.has_users_value

    async def create_user(self, username, password, platform_role):
        return ADMIN

    async def authenticate(self, username, password):
        return ADMIN if (username, password) == ("admin", "correct") else None

    async def update_profile(self, user_id, profile: UserProfileUpdate):
        return UserRecord(
            id=ADMIN.id,
            username=profile.username,
            platform_role=ADMIN.platform_role,
            status=ADMIN.status,
            display_name=profile.display_name,
            email=profile.email,
            phone=profile.phone,
            department=profile.department,
            job_title=profile.job_title,
            remark=profile.remark,
        )

    async def change_password(self, user_id, current_password, new_password):
        if current_password != "correct":
            raise CurrentPasswordIncorrectError()
        assert user_id == ADMIN.id
        assert new_password == "NewPass!2026"


class FakeSessions:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []

    async def issue(self, user, client_info):
        return issued()

    async def refresh(self, token):
        self.refresh_calls.append(token)
        return (
            issued("access-two", "refresh-two")
            if token == "refresh-one"
            else None
        )

    async def revoke_current(self, token):
        return token == "refresh-one"

    async def revoke_all(self, user_id):
        return 2

    async def list_sessions(self, user_id):
        return [SESSION]


class FakePreferences:
    async def get_or_create(self, user_id):
        return UserPreferences(
            user_id=user_id, language="zh-CN", timezone="Asia/Shanghai"
        )

    async def update(self, user_id, *, language, timezone):
        return UserPreferences(
            user_id=user_id, language=language, timezone=timezone
        )


class FakeRuntime:
    def __init__(self) -> None:
        self.users = FakeUsers()
        self.sessions = FakeSessions()
        self.preferences = FakePreferences()


class FakeAudit:
    async def record(self, **_kwargs) -> None:
        return None


def build_client(monkeypatch, runtime: FakeRuntime) -> TestClient:
    async def initialized():
        return 0

    monkeypatch.setattr(auth_router, "initialize_admin_agents", initialized)
    monkeypatch.setattr(
        auth_router, "is_multi_user_enabled", lambda: True, raising=False
    )
    monkeypatch.setattr(
        auth_router, "get_identity_runtime", lambda: runtime, raising=False
    )
    monkeypatch.setattr(
        me_router, "get_identity_runtime", lambda: runtime, raising=False
    )
    app = FastAPI()

    @app.middleware("http")
    async def inject_identity(request: Request, call_next):
        request.state.authenticated_session = AuthenticatedSession(
            user=ADMIN,
            session=SESSION,
        )
        return await call_next(request)

    app.include_router(auth_router.router, prefix="/api")
    app.include_router(me_router.router, prefix="/api")
    app.dependency_overrides[me_router.get_user_audit_repository] = FakeAudit
    return TestClient(app)


def test_incomplete_first_registration_can_recover_on_login(monkeypatch):
    runtime = FakeRuntime()
    runtime.users.has_users_value = False
    client = build_client(monkeypatch, runtime)

    async def fail():
        raise RuntimeError("secret-dsn")

    monkeypatch.setattr(auth_router, "initialize_admin_agents", fail)
    response = client.post(
        "/api/auth/register", json={"username": "admin", "password": "correct"}
    )
    assert response.status_code == 503
    assert "secret-dsn" not in response.text
    assert "set-cookie" not in response.headers

    async def ready():
        return 2

    monkeypatch.setattr(auth_router, "initialize_admin_agents", ready)
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct"}
    )
    assert response.status_code == 200
    assert response.json()["token"]


def test_multi_user_login_sets_http_only_refresh_cookie_and_returns_user(
    monkeypatch,
) -> None:
    client = build_client(monkeypatch, FakeRuntime())

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct"},
        headers={"user-agent": "pytest"},
    )

    assert response.status_code == 200
    assert response.json()["token"] == "access-one"
    assert response.json()["user"] == {
        "id": str(ADMIN.id),
        "username": "admin",
        "platform_role": "admin",
        "status": "active",
        "display_name": None,
        "email": None,
        "phone": None,
        "department": None,
        "job_title": None,
        "remark": None,
        "created_at": None,
        "updated_at": None,
        "last_login_at": None,
    }
    cookie = response.headers["set-cookie"].lower()
    assert "qwenpaw_refresh_token=refresh-one" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/auth" in cookie


def test_refresh_rotates_cookie_and_returns_new_memory_access_token(
    monkeypatch,
) -> None:
    runtime = FakeRuntime()
    client = build_client(monkeypatch, runtime)
    client.cookies.set("qwenpaw_refresh_token", "refresh-one")

    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert response.json()["token"] == "access-two"
    assert runtime.sessions.refresh_calls == ["refresh-one"]
    assert (
        "qwenpaw_refresh_token=refresh-two" in response.headers["set-cookie"]
    )


def test_multi_user_verify_uses_authenticated_database_session(
    monkeypatch,
) -> None:
    client = build_client(monkeypatch, FakeRuntime())
    monkeypatch.setattr(
        auth_router,
        "verify_token",
        lambda _token: (_ for _ in ()).throw(
            AssertionError(
                "multi-user verify must not call legacy JWT verification"
            )
        ),
    )

    response = client.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer opaque-access-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"valid": True, "username": "admin"}


def test_first_registration_creates_admin_but_self_registration_stays_closed(
    monkeypatch,
) -> None:
    runtime = FakeRuntime()
    runtime.users.has_users_value = False
    client = build_client(monkeypatch, runtime)
    response = client.post(
        "/api/auth/register",
        json={"username": "owner", "password": "correct"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["platform_role"] == "admin"

    runtime.users.has_users_value = True
    rejected = client.post(
        "/api/auth/register",
        json={"username": "member", "password": "correct"},
    )
    assert rejected.status_code == 403


def test_me_preferences_sessions_logout_and_revoke_all(monkeypatch) -> None:
    client = build_client(monkeypatch, FakeRuntime())

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"
    assert me.json()["preferences"]["timezone"] == "Asia/Shanghai"

    updated = client.patch(
        "/api/me/preferences",
        json={"language": "en", "timezone": "UTC"},
    )
    assert updated.json() == {"language": "en", "timezone": "UTC"}

    sessions = client.get("/api/auth/sessions")
    assert sessions.status_code == 200
    assert sessions.json()[0]["id"] == str(SESSION.id)

    client.cookies.set("qwenpaw_refresh_token", "refresh-one")
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert "max-age=0" in logout.headers["set-cookie"].lower()

    revoked = client.post("/api/auth/revoke-all-tokens")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_sessions"] == 2


def test_current_user_updates_profile_without_accepting_governance_fields(
    monkeypatch,
) -> None:
    client = build_client(monkeypatch, FakeRuntime())

    updated = client.patch(
        "/api/me/profile",
        json={
            "username": "alice",
            "display_name": "Alice Chen",
            "email": "alice@example.com",
            "phone": "+86 138-0000-0000",
            "department": "研发部",
            "job_title": "平台工程师",
            "remark": "企业账户",
        },
    )
    rejected = client.patch(
        "/api/me/profile",
        json={"username": "alice", "platform_role": "admin"},
    )

    assert updated.status_code == 200
    assert updated.json()["user"]["display_name"] == "Alice Chen"
    assert updated.json()["user"]["department"] == "研发部"
    assert "password" not in updated.text.lower()
    assert rejected.status_code == 422


def test_current_user_change_password_requires_old_password_and_revokes_sessions(
    monkeypatch,
) -> None:
    client = build_client(monkeypatch, FakeRuntime())

    wrong = client.post(
        "/api/me/change-password",
        json={"current_password": "wrong", "new_password": "NewPass!2026"},
    )
    changed = client.post(
        "/api/me/change-password",
        json={"current_password": "correct", "new_password": "NewPass!2026"},
    )

    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "current_password_incorrect"
    assert changed.status_code == 200
    assert changed.json() == {"revoked_sessions": 2}
