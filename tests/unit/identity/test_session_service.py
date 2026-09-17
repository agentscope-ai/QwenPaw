# -*- coding: utf-8 -*-
"""多用户访问令牌、刷新会话和设备撤销契约。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qwenpaw.identity.models import PlatformRole, UserRecord
from qwenpaw.identity.sessions import (
    AuthenticatedSession,
    SessionRecord,
    SessionService,
)


class FakeSessionRepository:
    def __init__(self) -> None:
        self.by_access_hash: dict[str, AuthenticatedSession] = {}
        self.by_refresh_hash: dict[str, AuthenticatedSession] = {}
        self.stored_hashes: list[tuple[str, str]] = []

    async def create_session(
        self,
        *,
        user: UserRecord,
        access_token_hash: str,
        refresh_token_hash: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
        client_info: dict[str, str],
    ) -> SessionRecord:
        session = SessionRecord(
            id=uuid4(),
            user_id=user.id,
            client_info=client_info,
            created_at=datetime(2026, 8, 21, tzinfo=UTC),
            last_seen_at=None,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            revoked_at=None,
        )
        authenticated = AuthenticatedSession(user=user, session=session)
        self.by_access_hash[access_token_hash] = authenticated
        self.by_refresh_hash[refresh_token_hash] = authenticated
        self.stored_hashes.append((access_token_hash, refresh_token_hash))
        return session

    async def get_by_access_hash(
        self,
        access_token_hash: str,
    ) -> AuthenticatedSession | None:
        return self.by_access_hash.get(access_token_hash)

    async def rotate_by_refresh_hash(
        self,
        *,
        refresh_token_hash: str,
        new_access_token_hash: str,
        new_refresh_token_hash: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
        last_seen_at: datetime,
    ) -> AuthenticatedSession | None:
        authenticated = self.by_refresh_hash.pop(refresh_token_hash, None)
        if authenticated is None:
            return None
        for token_hash, candidate in list(self.by_access_hash.items()):
            if candidate.session.id == authenticated.session.id:
                del self.by_access_hash[token_hash]
        updated = replace(
            authenticated,
            session=replace(
                authenticated.session,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
                last_seen_at=last_seen_at,
            ),
        )
        self.by_access_hash[new_access_token_hash] = updated
        self.by_refresh_hash[new_refresh_token_hash] = updated
        self.stored_hashes.append((new_access_token_hash, new_refresh_token_hash))
        return updated

    async def revoke_by_refresh_hash(
        self,
        refresh_token_hash: str,
        revoked_at: datetime,
    ) -> bool:
        authenticated = self.by_refresh_hash.pop(refresh_token_hash, None)
        if authenticated is None:
            return False
        for token_hash, candidate in list(self.by_access_hash.items()):
            if candidate.session.id == authenticated.session.id:
                del self.by_access_hash[token_hash]
        return True

    async def revoke_all(self, user_id: UUID, revoked_at: datetime) -> int:
        session_ids = {
            item.session.id
            for item in self.by_refresh_hash.values()
            if item.user.id == user_id
        }
        self.by_refresh_hash = {
            key: item
            for key, item in self.by_refresh_hash.items()
            if item.session.id not in session_ids
        }
        self.by_access_hash = {
            key: item
            for key, item in self.by_access_hash.items()
            if item.session.id not in session_ids
        }
        return len(session_ids)

    async def list_for_user(self, user_id: UUID) -> list[SessionRecord]:
        unique = {
            item.session.id: item.session
            for item in self.by_refresh_hash.values()
            if item.user.id == user_id
        }
        return list(unique.values())


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


@pytest.fixture
def user() -> UserRecord:
    return UserRecord(
        id=uuid4(),
        username="admin",
        platform_role=PlatformRole.ADMIN,
        status="active",
    )


@pytest.mark.asyncio
async def test_issue_stores_only_hashes_and_authenticates_access_token(
    now: datetime,
    user: UserRecord,
) -> None:
    repository = FakeSessionRepository()
    service = SessionService(repository, clock=lambda: now)

    issued = await service.issue(user, {"user_agent": "acceptance"})
    authenticated = await service.authenticate_access(issued.access_token)

    assert authenticated is not None
    assert authenticated.user == user
    assert issued.refresh_token != issued.access_token
    assert all(
        issued.access_token not in value and issued.refresh_token not in value
        for pair in repository.stored_hashes
        for value in pair
    )


@pytest.mark.asyncio
async def test_refresh_rotates_both_tokens_and_rejects_reuse(
    now: datetime,
    user: UserRecord,
) -> None:
    repository = FakeSessionRepository()
    service = SessionService(repository, clock=lambda: now)
    first = await service.issue(user, {})

    second = await service.refresh(first.refresh_token)

    assert second is not None
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert await service.refresh(first.refresh_token) is None
    assert await service.authenticate_access(first.access_token) is None
    assert await service.authenticate_access(second.access_token) is not None


@pytest.mark.asyncio
async def test_expired_or_disabled_access_session_is_rejected(
    now: datetime,
    user: UserRecord,
) -> None:
    repository = FakeSessionRepository()
    service = SessionService(repository, clock=lambda: now)
    issued = await service.issue(user, {})
    token_hash = service.hash_token(issued.access_token)
    authenticated = repository.by_access_hash[token_hash]

    repository.by_access_hash[token_hash] = replace(
        authenticated,
        session=replace(
            authenticated.session,
            access_expires_at=now - timedelta(seconds=1),
        ),
    )
    assert await service.authenticate_access(issued.access_token) is None

    repository.by_access_hash[token_hash] = replace(
        authenticated,
        user=replace(user, status="disabled"),
    )
    assert await service.authenticate_access(issued.access_token) is None


@pytest.mark.asyncio
async def test_current_and_all_device_revocation(
    now: datetime,
    user: UserRecord,
) -> None:
    repository = FakeSessionRepository()
    service = SessionService(repository, clock=lambda: now)
    first = await service.issue(user, {"device": "one"})
    second = await service.issue(user, {"device": "two"})

    assert len(await service.list_sessions(user.id)) == 2
    assert await service.revoke_current(first.refresh_token) is True
    assert await service.authenticate_access(first.access_token) is None
    assert await service.authenticate_access(second.access_token) is not None

    assert await service.revoke_all(user.id) == 1
    assert await service.authenticate_access(second.access_token) is None
