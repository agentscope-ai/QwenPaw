# -*- coding: utf-8 -*-
"""管理员用户治理必须保护最后一个可用管理员。"""

from __future__ import annotations

from dataclasses import asdict, replace
from uuid import UUID, uuid4

import pytest

from qwenpaw.identity.governance import (
    LastActiveAdminError,
    UserGovernanceService,
    UserNotFoundError,
)
from qwenpaw.identity.models import PlatformRole, UserProfileUpdate, UserRecord


class FakeUsers:
    def __init__(self) -> None:
        self.admin = UserRecord(
            id=uuid4(),
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

    async def list_users(self) -> list[UserRecord]:
        return list(self.users.values())

    async def get_user(self, user_id: UUID) -> UserRecord:
        user = self.users.get(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    async def update_status(self, user_id: UUID, status: str) -> UserRecord:
        user = self.users.get(user_id)
        if user is None:
            raise UserNotFoundError()
        if (
            status == "disabled"
            and user.platform_role is PlatformRole.ADMIN
            and user.status == "active"
            and sum(
                1
                for candidate in self.users.values()
                if candidate.platform_role is PlatformRole.ADMIN
                and candidate.status == "active"
            )
            == 1
        ):
            raise LastActiveAdminError()
        updated = replace(user, status=status)
        self.users[user_id] = updated
        return updated

    async def update_role(
        self,
        user_id: UUID,
        role: PlatformRole,
    ) -> UserRecord:
        user = self.users.get(user_id)
        if user is None:
            raise UserNotFoundError()
        if (
            role is PlatformRole.MEMBER
            and user.platform_role is PlatformRole.ADMIN
            and user.status == "active"
            and sum(
                1
                for candidate in self.users.values()
                if candidate.platform_role is PlatformRole.ADMIN
                and candidate.status == "active"
            )
            == 1
        ):
            raise LastActiveAdminError()
        updated = replace(user, platform_role=role)
        self.users[user_id] = updated
        return updated


class FakeCreationService:
    def __init__(self, users: FakeUsers) -> None:
        self.users = users

    async def create_user(self, username, password, platform_role):
        user = UserRecord(
            id=uuid4(),
            username=username,
            platform_role=platform_role,
            status="active",
        )
        self.users.users[user.id] = user
        return user

    async def update_profile(self, user_id, profile):
        user = self.users.users[user_id]
        updated = replace(user, **asdict(profile))
        self.users.users[user_id] = updated
        return updated

    async def reset_password(self, user_id, new_password):
        assert user_id in self.users.users
        assert new_password == "NewPass!2026"


class FakeSessions:
    def __init__(self) -> None:
        self.revoked: list[UUID] = []

    async def revoke_all(self, user_id: UUID) -> int:
        self.revoked.append(user_id)
        return 2


def _service():
    users = FakeUsers()
    sessions = FakeSessions()
    return (
        UserGovernanceService(
            repository=users,
            user_service=FakeCreationService(users),
            session_service=sessions,
        ),
        users,
        sessions,
    )


@pytest.mark.asyncio
async def test_create_and_list_users_preserve_requested_role() -> None:
    service, _users, _sessions = _service()

    created = await service.create_user(
        "second-admin",
        "safe-password",
        PlatformRole.ADMIN,
    )
    listed = await service.list_users()

    assert created.platform_role is PlatformRole.ADMIN
    assert {user.username for user in listed} == {
        "admin",
        "member",
        "second-admin",
    }


@pytest.mark.asyncio
async def test_disabling_user_revokes_all_sessions() -> None:
    service, users, sessions = _service()

    updated, revoked = await service.set_status(users.member.id, "disabled")

    assert updated.status == "disabled"
    assert revoked == 2
    assert sessions.revoked == [users.member.id]


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_disabled_or_demoted() -> None:
    service, users, _sessions = _service()

    with pytest.raises(LastActiveAdminError, match="last_active_admin"):
        await service.set_status(users.admin.id, "disabled")
    with pytest.raises(LastActiveAdminError, match="last_active_admin"):
        await service.set_role(users.admin.id, PlatformRole.MEMBER)


@pytest.mark.asyncio
async def test_explicit_session_reset_does_not_change_user_status() -> None:
    service, users, sessions = _service()

    revoked = await service.revoke_sessions(users.member.id)

    assert revoked == 2
    assert users.users[users.member.id].status == "active"
    assert sessions.revoked == [users.member.id]


@pytest.mark.asyncio
async def test_explicit_session_reset_rejects_unknown_user() -> None:
    service, _users, sessions = _service()

    with pytest.raises(UserNotFoundError, match="user_not_found"):
        await service.revoke_sessions(uuid4())

    assert sessions.revoked == []


@pytest.mark.asyncio
async def test_governance_updates_profile_without_revoking_sessions() -> None:
    service, users, sessions = _service()

    updated = await service.update_profile(
        users.member.id,
        UserProfileUpdate(username="renamed", department="研发部"),
    )

    assert updated.username == "renamed"
    assert updated.department == "研发部"
    assert sessions.revoked == []


@pytest.mark.asyncio
async def test_governance_reset_password_revokes_all_sessions() -> None:
    service, users, sessions = _service()

    revoked = await service.reset_password(users.member.id, "NewPass!2026")

    assert revoked == 2
    assert sessions.revoked == [users.member.id]
