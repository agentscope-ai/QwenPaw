"""管理员用户治理 API 的角色边界与响应契约。"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import admin_users
from qwenpaw.identity.governance import LastActiveAdminError, UserNotFoundError
from qwenpaw.identity.models import PlatformRole, UserProfileUpdate, UserRecord

ADMIN = ActorContext(
    user_id=uuid4(),
    actor_type=ActorType.USER,
    platform_role=PlatformRole.ADMIN,
    admin_mode=False,
    request_id="req-admin",
)
MEMBER = replace(ADMIN, platform_role=PlatformRole.MEMBER, request_id="req-member")


class FakeGovernance:
    def __init__(self) -> None:
        self.admin = UserRecord(
            id=ADMIN.user_id,
            username="admin",
            platform_role=PlatformRole.ADMIN,
            status="active",
        )
        self.member = UserRecord(
            id=uuid4(),
            username="member",
            platform_role=PlatformRole.MEMBER,
            status="active",
        )
        self.users = {self.admin.id: self.admin, self.member.id: self.member}

    async def list_users(self):
        return list(self.users.values())

    async def create_user(self, username, password, platform_role):
        user = UserRecord(
            id=uuid4(),
            username=username,
            platform_role=platform_role,
            status="active",
        )
        self.users[user.id] = user
        return user

    async def set_status(self, user_id: UUID, status: str):
        user = self.users[user_id]
        if user.id == self.admin.id and status == "disabled":
            raise LastActiveAdminError()
        updated = replace(user, status=status)
        self.users[user_id] = updated
        return updated, 3 if status == "disabled" else 0

    async def set_role(self, user_id: UUID, role: PlatformRole):
        updated = replace(self.users[user_id], platform_role=role)
        self.users[user_id] = updated
        return updated

    async def revoke_sessions(self, user_id: UUID):
        if user_id not in self.users:
            raise UserNotFoundError()
        return 2
    async def update_profile(self, user_id: UUID, profile: UserProfileUpdate):
        updated = replace(self.users[user_id], **{
            field: getattr(profile, field)
            for field in (
                "username", "display_name", "email", "phone", "department",
                "job_title", "remark",
            )
        })
        self.users[user_id] = updated
        return updated

    async def reset_password(self, user_id: UUID, new_password: str):
        assert user_id in self.users
        assert new_password == "NewPass!2026"
        return 2


class FakeAudit:
    async def record(self, **_kwargs) -> None:
        return None


def _client(actor: ActorContext) -> tuple[TestClient, FakeGovernance]:
    app = FastAPI()
    service = FakeGovernance()
    app.include_router(admin_users.router, prefix="/api")
    app.dependency_overrides[admin_users.get_actor] = lambda: actor
    app.dependency_overrides[admin_users.require_multi_user_mode] = lambda: None
    app.dependency_overrides[admin_users.get_governance_service] = lambda: service
    app.dependency_overrides[admin_users.get_user_audit_repository] = FakeAudit
    return TestClient(app), service


def test_member_cannot_list_or_create_platform_users() -> None:
    client, _service = _client(MEMBER)

    assert client.get("/api/admin/users").status_code == 403
    assert (
        client.post(
            "/api/admin/users",
            json={
                "username": "new-member",
                "password": "member-password",
                "platform_role": "member",
            },
        ).status_code
        == 403
    )


def test_admin_lists_and_creates_users_without_exposing_password_data() -> None:
    client, _service = _client(ADMIN)

    listed = client.get("/api/admin/users")
    created = client.post(
        "/api/admin/users",
        json={
            "username": "second-admin",
            "password": "admin-password",
            "platform_role": "admin",
        },
    )

    assert listed.status_code == 200
    assert {row["username"] for row in listed.json()} == {"admin", "member"}
    assert created.status_code == 201
    assert created.json()["platform_role"] == "admin"
    assert "password" not in created.text.lower()


def test_admin_can_disable_enable_change_role_and_revoke_sessions() -> None:
    client, service = _client(ADMIN)
    member_id = service.member.id

    disabled = client.patch(
        f"/api/admin/users/{member_id}/status",
        json={"status": "disabled"},
    )
    enabled = client.patch(
        f"/api/admin/users/{member_id}/status",
        json={"status": "active"},
    )
    promoted = client.patch(
        f"/api/admin/users/{member_id}/role",
        json={"platform_role": "admin"},
    )
    revoked = client.post(f"/api/admin/users/{member_id}/revoke-sessions")

    assert disabled.json()["revoked_sessions"] == 3
    assert enabled.json()["user"]["status"] == "active"
    assert promoted.json()["platform_role"] == "admin"
    assert revoked.json() == {"revoked_sessions": 2}


def test_last_active_admin_protection_is_a_conflict() -> None:
    client, service = _client(ADMIN)

    response = client.patch(
        f"/api/admin/users/{service.admin.id}/status",
        json={"status": "disabled"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "last_active_admin"


def test_revoke_sessions_returns_not_found_for_unknown_user() -> None:
    client, _service = _client(ADMIN)

    response = client.post(f"/api/admin/users/{uuid4()}/revoke-sessions")

    assert response.status_code == 404
    assert response.json()["detail"] == "user_not_found"


def test_admin_updates_profile_and_resets_password_without_exposing_secret() -> None:
    client, service = _client(ADMIN)
    member_id = service.member.id

    updated = client.patch(
        f"/api/admin/users/{member_id}/profile",
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
    reset = client.post(
        f"/api/admin/users/{member_id}/reset-password",
        json={"new_password": "NewPass!2026"},
    )

    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Alice Chen"
    assert reset.status_code == 200
    assert reset.json() == {"revoked_sessions": 2}
    assert "password" not in updated.text.lower()
    assert "password" not in reset.text.lower()


def test_member_cannot_edit_profile_or_reset_password() -> None:
    client, service = _client(MEMBER)
    member_id = service.member.id

    assert client.patch(
        f"/api/admin/users/{member_id}/profile",
        json={"username": "alice"},
    ).status_code == 403
    assert client.post(
        f"/api/admin/users/{member_id}/reset-password",
        json={"new_password": "NewPass!2026"},
    ).status_code == 403
