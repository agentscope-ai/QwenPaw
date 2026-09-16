# -*- coding: utf-8 -*-
"""多用户访问令牌与刷新会话领域服务。"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from .models import UserRecord


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """不包含任何明文令牌的设备会话。"""

    id: UUID
    user_id: UUID
    client_info: dict[str, str]
    created_at: datetime
    last_seen_at: datetime | None
    access_expires_at: datetime
    refresh_expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """一次已验证请求对应的用户与设备会话。"""

    user: UserRecord
    session: SessionRecord


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """只在签发响应边界短暂存在的明文令牌。"""

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    authenticated: AuthenticatedSession


class SessionRepository(Protocol):
    async def create_session(
        self,
        *,
        user: UserRecord,
        access_token_hash: str,
        refresh_token_hash: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
        client_info: dict[str, str],
    ) -> SessionRecord: ...

    async def get_by_access_hash(
        self,
        access_token_hash: str,
    ) -> AuthenticatedSession | None: ...

    async def rotate_by_refresh_hash(
        self,
        *,
        refresh_token_hash: str,
        new_access_token_hash: str,
        new_refresh_token_hash: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
        last_seen_at: datetime,
    ) -> AuthenticatedSession | None: ...

    async def revoke_by_refresh_hash(
        self,
        refresh_token_hash: str,
        revoked_at: datetime,
    ) -> bool: ...

    async def revoke_all(self, user_id: UUID, revoked_at: datetime) -> int: ...

    async def list_for_user(self, user_id: UUID) -> list[SessionRecord]: ...


class SessionService:
    """签发、验证、轮换和撤销随机不透明令牌。"""

    def __init__(
        self,
        repository: SessionRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=30),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._token_factory = token_factory

    @staticmethod
    def hash_token(token: str) -> str:
        """生成适合数据库等值查询的不可逆令牌摘要。"""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def issue(
        self,
        user: UserRecord,
        client_info: dict[str, str],
    ) -> IssuedSession:
        now = self._clock()
        access_token = self._token_factory()
        refresh_token = self._token_factory()
        access_expires_at = now + self._access_ttl
        refresh_expires_at = now + self._refresh_ttl
        session = await self._repository.create_session(
            user=user,
            access_token_hash=self.hash_token(access_token),
            refresh_token_hash=self.hash_token(refresh_token),
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            client_info=client_info,
        )
        return IssuedSession(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            authenticated=AuthenticatedSession(user=user, session=session),
        )

    async def authenticate_access(
        self,
        access_token: str,
    ) -> AuthenticatedSession | None:
        if not access_token:
            return None
        authenticated = await self._repository.get_by_access_hash(
            self.hash_token(access_token)
        )
        if authenticated is None:
            return None
        now = self._clock()
        if (
            authenticated.user.status != "active"
            or authenticated.session.revoked_at is not None
            or authenticated.session.access_expires_at <= now
        ):
            return None
        return authenticated

    async def refresh(self, refresh_token: str) -> IssuedSession | None:
        if not refresh_token:
            return None
        now = self._clock()
        access_token = self._token_factory()
        next_refresh_token = self._token_factory()
        access_expires_at = now + self._access_ttl
        refresh_expires_at = now + self._refresh_ttl
        authenticated = await self._repository.rotate_by_refresh_hash(
            refresh_token_hash=self.hash_token(refresh_token),
            new_access_token_hash=self.hash_token(access_token),
            new_refresh_token_hash=self.hash_token(next_refresh_token),
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            last_seen_at=now,
        )
        if authenticated is None or authenticated.user.status != "active":
            return None
        return IssuedSession(
            access_token=access_token,
            refresh_token=next_refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            authenticated=authenticated,
        )

    async def revoke_current(self, refresh_token: str) -> bool:
        if not refresh_token:
            return False
        return await self._repository.revoke_by_refresh_hash(
            self.hash_token(refresh_token),
            self._clock(),
        )

    async def revoke_all(self, user_id: UUID) -> int:
        return await self._repository.revoke_all(user_id, self._clock())

    async def list_sessions(self, user_id: UUID) -> list[SessionRecord]:
        return await self._repository.list_for_user(user_id)
