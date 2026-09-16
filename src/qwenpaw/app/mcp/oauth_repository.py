# -*- coding: utf-8 -*-
"""PostgreSQL persistence for single-use MCP OAuth state."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_SAFE_SCHEMA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OAuthSessionConflictError(RuntimeError):
    """The OAuth state is missing, expired, consumed, or no longer authorized."""


@dataclass(frozen=True, slots=True)
class OAuthSessionRecord:
    id: UUID
    driver_id: UUID
    initiated_by: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OAuthSessionStatus:
    status: str
    expires_at: datetime


class PostgresOAuthRepository:
    """Store only hashed OAuth state; the PKCE verifier remains in memory."""

    def __init__(self, *, schema: str) -> None:
        if not _SAFE_SCHEMA.fullmatch(schema):
            raise ValueError("Invalid database schema")
        prefix = f'"{schema}".'
        self._sessions = f'{prefix}"mcp_oauth_sessions"'
        self._drivers = f'{prefix}"agent_drivers"'
        self._agents = f'{prefix}"agents"'
        self._members = f'{prefix}"agent_members"'
        self._users = f'{prefix}"users"'

    @staticmethod
    def state_hash(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    async def create(
        self,
        *,
        session: AsyncSession,
        state: str,
        driver_id: UUID,
        initiated_by: UUID,
        expires_at: datetime,
    ) -> UUID:
        session_id = uuid4()
        await session.execute(
            text(
                f"INSERT INTO {self._sessions} "
                "(id, driver_id, initiated_by, state_hash, status, expires_at) "
                "VALUES (:id, :driver_id, :initiated_by, :state_hash, "
                "'pending', :expires_at)"
            ),
            {
                "id": session_id,
                "driver_id": driver_id,
                "initiated_by": initiated_by,
                "state_hash": self.state_hash(state),
                "expires_at": expires_at,
            },
        )
        return session_id

    async def consume(
        self,
        *,
        session: AsyncSession,
        state: str,
        driver_id: UUID,
        initiated_by: UUID,
    ) -> OAuthSessionRecord:
        """Atomically consume state after rechecking user and edit membership."""
        result = await session.execute(
            text(
                "WITH authorized AS (SELECT driver.id AS driver_id "
                f"FROM {self._drivers} AS driver "
                f"JOIN {self._agents} AS agent ON agent.id = driver.agent_id "
                f"JOIN {self._users} AS usr ON usr.id = :initiated_by "
                f"LEFT JOIN {self._members} AS member ON "
                "member.agent_id = agent.id AND member.user_id = usr.id "
                "WHERE driver.id = :driver_id "
                "AND usr.status = 'active' AND agent.status = 'active' "
                "AND driver.status NOT IN ('deleted', 'disabled') "
                "AND (agent.owner_user_id = usr.id OR "
                "(member.role = 'collaborator' AND member.revoked_at IS NULL))"
                ") "
                f"UPDATE {self._sessions} AS oauth SET "
                "status = 'consumed', completed_at = now() "
                "FROM authorized "
                "WHERE oauth.driver_id = authorized.driver_id "
                "AND oauth.driver_id = :driver_id "
                "AND oauth.initiated_by = :initiated_by "
                "AND oauth.state_hash = :state_hash "
                "AND oauth.status = 'pending' AND oauth.expires_at > now() "
                "RETURNING oauth.id, oauth.driver_id, oauth.initiated_by, "
                "oauth.expires_at"
            ),
            {
                "state_hash": self.state_hash(state),
                "driver_id": driver_id,
                "initiated_by": initiated_by,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise OAuthSessionConflictError("oauth_session_invalid")
        return OAuthSessionRecord(
            id=row["id"],
            driver_id=row["driver_id"],
            initiated_by=row["initiated_by"],
            expires_at=row["expires_at"],
        )

    async def fail(
        self,
        *,
        session: AsyncSession,
        state: str,
        driver_id: UUID,
        initiated_by: UUID,
    ) -> bool:
        """Terminally invalidate a still-pending callback without secrets."""
        result = await session.execute(
            text(
                f"UPDATE {self._sessions} SET status = 'failed', "
                "completed_at = now() WHERE state_hash = :state_hash "
                "AND driver_id = :driver_id AND initiated_by = :initiated_by "
                "AND status = 'pending' RETURNING id"
            ),
            {
                "state_hash": self.state_hash(state),
                "driver_id": driver_id,
                "initiated_by": initiated_by,
            },
        )
        return result.mappings().one_or_none() is not None

    async def status(
        self,
        *,
        session: AsyncSession,
        state: str,
        driver_id: UUID,
        initiated_by: UUID,
    ) -> OAuthSessionStatus | None:
        result = await session.execute(
            text(
                f"SELECT status, expires_at FROM {self._sessions} "
                "WHERE state_hash = :state_hash AND driver_id = :driver_id "
                "AND initiated_by = :initiated_by"
            ),
            {
                "state_hash": self.state_hash(state),
                "driver_id": driver_id,
                "initiated_by": initiated_by,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        status = str(row["status"])
        expires_at = row["expires_at"]
        if status == "pending" and expires_at <= datetime.now(expires_at.tzinfo):
            status = "expired"
        elif status == "consumed":
            status = "completed"
        elif status != "pending":
            status = "failed"
        return OAuthSessionStatus(status=status, expires_at=expires_at)
