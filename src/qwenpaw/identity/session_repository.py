# -*- coding: utf-8 -*-
"""PostgreSQL 多用户设备会话 Repository。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session
from .models import PlatformRole, UserRecord
from .sessions import AuthenticatedSession, SessionRecord

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PostgresSessionRepository:
    """使用哈希令牌查询并原子轮换设备会话。"""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self._sessions = f'"{normalized}".user_sessions'
        self._users = f'"{normalized}".users'
        self._session_factory = session_factory

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
        session_id = uuid4()
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self._sessions} "
                    "(id, user_id, access_token_hash, refresh_token_hash, "
                    "access_expires_at, expires_at, client_info) VALUES "
                    "(:id, :user_id, :access_hash, :refresh_hash, "
                    ":access_expires_at, :refresh_expires_at, "
                    "CAST(:client_info AS jsonb)) RETURNING id, user_id, "
                    "client_info, created_at, last_seen_at, "
                    "access_expires_at, expires_at, revoked_at"
                ),
                {
                    "id": session_id,
                    "user_id": user.id,
                    "access_hash": access_token_hash,
                    "refresh_hash": refresh_token_hash,
                    "access_expires_at": access_expires_at,
                    "refresh_expires_at": refresh_expires_at,
                    "client_info": json.dumps(client_info, ensure_ascii=False),
                },
            )
            return _session_from_row(result.mappings().one())

    async def get_by_access_hash(
        self,
        access_token_hash: str,
    ) -> AuthenticatedSession | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(self._select_joined("s.access_token_hash = :token_hash")),
                {"token_hash": access_token_hash},
            )
            row = result.mappings().one_or_none()
        return _authenticated_from_row(row) if row is not None else None

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
        async with self._session_factory() as session:
            selected = await session.execute(
                text(
                    self._select_joined(
                        "s.refresh_token_hash = :refresh_hash "
                        "AND s.revoked_at IS NULL "
                        "AND s.expires_at > :now "
                        "AND u.status = 'active'"
                    )
                    + " FOR UPDATE OF s"
                ),
                {"refresh_hash": refresh_token_hash, "now": last_seen_at},
            )
            row = selected.mappings().one_or_none()
            if row is None:
                return None
            await session.execute(
                text(
                    f"UPDATE {self._sessions} SET "
                    "access_token_hash = :access_hash, "
                    "refresh_token_hash = :next_refresh_hash, "
                    "access_expires_at = :access_expires_at, "
                    "expires_at = :refresh_expires_at, "
                    "last_seen_at = :last_seen_at "
                    "WHERE id = :session_id"
                ),
                {
                    "session_id": row["session_id"],
                    "access_hash": new_access_token_hash,
                    "next_refresh_hash": new_refresh_token_hash,
                    "access_expires_at": access_expires_at,
                    "refresh_expires_at": refresh_expires_at,
                    "last_seen_at": last_seen_at,
                },
            )
        updated = dict(row)
        updated.update(
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            last_seen_at=last_seen_at,
        )
        return _authenticated_from_row(updated)

    async def revoke_by_refresh_hash(
        self,
        refresh_token_hash: str,
        revoked_at: datetime,
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"UPDATE {self._sessions} SET revoked_at = :revoked_at "
                    "WHERE refresh_token_hash = :refresh_hash "
                    "AND revoked_at IS NULL RETURNING id"
                ),
                {
                    "refresh_hash": refresh_token_hash,
                    "revoked_at": revoked_at,
                },
            )
            return result.scalar_one_or_none() is not None

    async def revoke_all(self, user_id: UUID, revoked_at: datetime) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"UPDATE {self._sessions} SET revoked_at = :revoked_at "
                    "WHERE user_id = :user_id AND revoked_at IS NULL "
                    "RETURNING id"
                ),
                {"user_id": user_id, "revoked_at": revoked_at},
            )
            return len(result.scalars().all())

    async def list_for_user(self, user_id: UUID) -> list[SessionRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, user_id, client_info, created_at, "
                    "last_seen_at, access_expires_at, expires_at, revoked_at "
                    f"FROM {self._sessions} WHERE user_id = :user_id "
                    "ORDER BY created_at DESC"
                ),
                {"user_id": user_id},
            )
            return [_session_from_row(row) for row in result.mappings().all()]

    def _select_joined(self, condition: str) -> str:
        return (
            "SELECT s.id AS session_id, s.user_id, s.client_info, "
            "s.created_at, s.last_seen_at, s.access_expires_at, "
            "s.expires_at AS refresh_expires_at, s.revoked_at, "
            "u.id, u.username, u.display_name, u.email, u.phone, "
            "u.department, u.job_title, u.remark, u.platform_role, u.status, "
            "u.created_at AS user_created_at, "
            "u.updated_at AS user_updated_at, u.last_login_at "
            f"FROM {self._sessions} AS s JOIN {self._users} AS u "
            f"ON u.id = s.user_id WHERE {condition}"
        )


def _session_from_row(row) -> SessionRecord:
    return SessionRecord(
        id=row.get("session_id", row.get("id")),
        user_id=row["user_id"],
        client_info=dict(row["client_info"] or {}),
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        access_expires_at=row["access_expires_at"],
        refresh_expires_at=row.get("refresh_expires_at", row.get("expires_at")),
        revoked_at=row["revoked_at"],
    )


def _authenticated_from_row(row) -> AuthenticatedSession:
    return AuthenticatedSession(
        user=UserRecord(
            id=row["id"],
            username=row["username"],
            platform_role=PlatformRole(row["platform_role"]),
            status="active" if row["status"] == "active" else "disabled",
            display_name=row.get("display_name"),
            email=row.get("email"),
            phone=row.get("phone"),
            department=row.get("department"),
            job_title=row.get("job_title"),
            remark=row.get("remark"),
            created_at=row.get("user_created_at"),
            updated_at=row.get("user_updated_at"),
            last_login_at=row.get("last_login_at"),
        ),
        session=_session_from_row(row),
    )
