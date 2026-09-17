# -*- coding: utf-8 -*-
"""Agent 用户私有运行空间 PostgreSQL 仓储。"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..access.agent_repository import agent_database_id
from ..memory_scope.models import (
    MemoryIndexState,
    MemoryScope,
    MemoryWorkspaceStatus,
)
from .database import database_session

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


@dataclass(frozen=True, slots=True)
class AgentUserWorkspaceRecord:
    user_id: UUID
    agent_key: str
    scope: MemoryScope
    workspace_key: str
    status: MemoryWorkspaceStatus
    index_state: MemoryIndexState
    index_version: int
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime


class AgentUserWorkspaceRepository:
    """以 user_id + agent_id + scope 为隔离键保存运行空间元数据。"""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _SAFE_SCHEMA.fullmatch(schema):
            raise ValueError("invalid_schema")
        self._table = f'"{schema}".agent_user_workspaces'
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def ensure_private(
        self,
        *,
        user_id: UUID,
        agent_key: str,
        workspace_key: str,
    ) -> AgentUserWorkspaceRecord:
        now = self._clock()
        statement = text(f"""
            INSERT INTO {self._table} (
                user_id, agent_id, scope, workspace_key, status,
                index_state, index_version, created_at, updated_at,
                last_accessed_at
            ) VALUES (
                :user_id, :agent_id, 'private', :workspace_key, 'active',
                'needs_reindex', 0, :now, :now, :now
            )
            ON CONFLICT (user_id, agent_id, scope) DO UPDATE SET
                last_accessed_at = EXCLUDED.last_accessed_at,
                updated_at = EXCLUDED.updated_at
            RETURNING user_id, :agent_key AS agent_key, scope, workspace_key,
                status, index_state, index_version, created_at, updated_at,
                last_accessed_at
            """)
        params = {
            "user_id": user_id,
            "agent_id": agent_database_id(agent_key),
            "agent_key": agent_key,
            "workspace_key": workspace_key,
            "now": now,
        }
        async with self._session_factory() as session:
            row = (await session.execute(statement, params)).mappings().one()
        return self._record(row)

    async def get_private(
        self,
        *,
        user_id: UUID,
        agent_key: str,
    ) -> AgentUserWorkspaceRecord | None:
        statement = text(f"""
            SELECT user_id, :agent_key AS agent_key, scope, workspace_key,
                status, index_state, index_version, created_at, updated_at,
                last_accessed_at
            FROM {self._table}
            WHERE user_id = :user_id
              AND agent_id = :agent_id
              AND scope = 'private'
            """)
        params = {
            "user_id": user_id,
            "agent_id": agent_database_id(agent_key),
            "agent_key": agent_key,
        }
        async with self._session_factory() as session:
            row = (await session.execute(statement, params)).mappings().one_or_none()
        return None if row is None else self._record(row)

    async def update_index_state(
        self,
        *,
        user_id: UUID,
        agent_key: str,
        index_state: MemoryIndexState,
        index_version: int,
    ) -> AgentUserWorkspaceRecord:
        now = self._clock()
        statement = text(f"""
            UPDATE {self._table}
            SET index_state = :index_state,
                index_version = :index_version,
                updated_at = :now,
                last_accessed_at = :now
            WHERE user_id = :user_id
              AND agent_id = :agent_id
              AND scope = 'private'
            RETURNING user_id, :agent_key AS agent_key, scope, workspace_key,
                status, index_state, index_version, created_at, updated_at,
                last_accessed_at
            """)
        params = {
            "user_id": user_id,
            "agent_id": agent_database_id(agent_key),
            "agent_key": agent_key,
            "index_state": index_state.value,
            "index_version": index_version,
            "now": now,
        }
        async with self._session_factory() as session:
            row = (await session.execute(statement, params)).mappings().one()
        return self._record(row)

    async def update_status(
        self,
        *,
        user_id: UUID,
        agent_key: str,
        status: MemoryWorkspaceStatus,
    ) -> AgentUserWorkspaceRecord:
        """更新一个明确用户在明确 Agent 下的私有空间生命周期。"""
        now = self._clock()
        statement = text(f"""
            UPDATE {self._table}
            SET status = :status, updated_at = :now
            WHERE user_id = :user_id
              AND agent_id = :agent_id
              AND scope = 'private'
            RETURNING user_id, :agent_key AS agent_key, scope, workspace_key,
                status, index_state, index_version, created_at, updated_at,
                last_accessed_at
            """)
        params = {
            "user_id": user_id,
            "agent_id": agent_database_id(agent_key),
            "agent_key": agent_key,
            "status": status.value,
            "now": now,
        }
        async with self._session_factory() as session:
            row = (await session.execute(statement, params)).mappings().one()
        return self._record(row)

    async def mark_agent_cleanup_pending(self, *, agent_key: str) -> int:
        """Agent 软删除时仅标记关联私有空间，保留物理文件。"""
        now = self._clock()
        statement = text(f"""
            UPDATE {self._table}
            SET status = 'cleanup_pending', updated_at = :now
            WHERE agent_id = :agent_id
              AND scope = 'private'
              AND status <> 'cleanup_pending'
            """)
        params = {
            "agent_id": agent_database_id(agent_key),
            "now": now,
        }
        async with self._session_factory() as session:
            result = await session.execute(statement, params)
        return int(result.rowcount or 0)

    @staticmethod
    def _record(row: dict) -> AgentUserWorkspaceRecord:
        return AgentUserWorkspaceRecord(
            user_id=row["user_id"],
            agent_key=row["agent_key"],
            scope=MemoryScope(row["scope"]),
            workspace_key=row["workspace_key"],
            status=MemoryWorkspaceStatus(row["status"]),
            index_state=MemoryIndexState(row["index_state"]),
            index_version=row["index_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
        )
