from __future__ import annotations

import re
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session, set_request_user
from .models import AgentArtifact

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PostgresArtifactRepository:
    def __init__(self, *, schema: str = "qwenpaw", session_factory: SessionFactory = database_session) -> None:
        if not _SAFE_SCHEMA.fullmatch(schema):
            raise ValueError("invalid_database_schema")
        self._table = f'"{schema}".user_agent_artifacts'
        self._sessions = session_factory

    async def register(self, artifact: AgentArtifact) -> AgentArtifact:
        statement = text(f"INSERT INTO {self._table} (id,owner_user_id,agent_id,conversation_id,relative_path,original_name,media_type,size,sha256,source_tool,status,created_at,deleted_at) VALUES (:id,:owner_user_id,:agent_id,:conversation_id,:relative_path,:original_name,:media_type,:size,:sha256,:source_tool,:status,:created_at,:deleted_at) RETURNING *")
        async with self._sessions() as session:
            await set_request_user(session, artifact.owner_user_id)
            # 同一内容键的跨进程登记串行化，事务内重查，防止重复工具/结束钩子竞争。
            lock_key = int.from_bytes(hashlib.sha256(f"{artifact.owner_user_id}:{artifact.agent_id}:{artifact.conversation_id}:{artifact.sha256}".encode()).digest()[:8], "big", signed=True)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
            existing = (await session.execute(text(
                f"SELECT * FROM {self._table} WHERE owner_user_id=:owner_user_id AND agent_id=:agent_id "
                "AND conversation_id IS NOT DISTINCT FROM :conversation_id AND sha256=:sha256 "
                "AND (status='active' OR (:automatic AND status='deleted')) "
                "ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, created_at ASC LIMIT 1"
            ), {"owner_user_id": artifact.owner_user_id, "agent_id": artifact.agent_id,
                "conversation_id": artifact.conversation_id, "sha256": artifact.sha256,
                "automatic": artifact.source_tool == "session_artifact_collector"})).mappings().one_or_none()
            if existing is not None:
                return self._from_row(existing)
            row = (await session.execute(statement, artifact.__dict__ if hasattr(artifact, "__dict__") else {field: getattr(artifact, field) for field in artifact.__dataclass_fields__})).mappings().one()
        return self._from_row(row)

    async def find_active_by_content(self, *, owner_user_id: UUID, agent_id: UUID, conversation_id: UUID | None, sha256: str) -> AgentArtifact | None:
        statement = text(
            f"SELECT * FROM {self._table} "
            "WHERE owner_user_id=:owner_user_id AND agent_id=:agent_id "
            "AND conversation_id IS NOT DISTINCT FROM :conversation_id "
            "AND sha256=:sha256 AND status='active' ORDER BY created_at ASC LIMIT 1"
        )
        async with self._sessions() as session:
            await set_request_user(session, owner_user_id)
            row = (await session.execute(statement, {
                "owner_user_id": owner_user_id,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "sha256": sha256,
            })).mappings().one_or_none()
        return None if row is None else self._from_row(row)

    async def find_deleted_by_content(self, *, owner_user_id: UUID, agent_id: UUID, conversation_id: UUID | None, sha256: str) -> AgentArtifact | None:
        async with self._sessions() as session:
            await set_request_user(session, owner_user_id)
            row = (await session.execute(text(
                f"SELECT * FROM {self._table} WHERE owner_user_id=:owner_user_id AND agent_id=:agent_id "
                "AND conversation_id IS NOT DISTINCT FROM :conversation_id AND sha256=:sha256 "
                "AND status='deleted' ORDER BY deleted_at DESC LIMIT 1"
            ), {"owner_user_id": owner_user_id, "agent_id": agent_id, "conversation_id": conversation_id, "sha256": sha256})).mappings().one_or_none()
        return None if row is None else self._from_row(row)

    async def list_active(self, *, owner_user_id: UUID, agent_id: UUID) -> list[AgentArtifact]:
        async with self._sessions() as session:
            await set_request_user(session, owner_user_id)
            rows = (await session.execute(text(f"SELECT * FROM {self._table} WHERE owner_user_id=:owner_user_id AND agent_id=:agent_id AND status='active' ORDER BY created_at DESC"), {"owner_user_id": owner_user_id, "agent_id": agent_id})).mappings().all()
        return [self._from_row(row) for row in rows]

    async def get(self, *, owner_user_id: UUID, artifact_id: UUID) -> AgentArtifact | None:
        async with self._sessions() as session:
            await set_request_user(session, owner_user_id)
            row = (await session.execute(text(f"SELECT * FROM {self._table} WHERE owner_user_id=:owner_user_id AND id=:id"), {"owner_user_id": owner_user_id, "id": artifact_id})).mappings().one_or_none()
        return None if row is None else self._from_row(row)

    async def mark_deleted(self, *, owner_user_id: UUID, artifact_id: UUID, deleted_at) -> AgentArtifact | None:
        async with self._sessions() as session:
            await set_request_user(session, owner_user_id)
            row = (await session.execute(text(f"UPDATE {self._table} SET status='deleted', deleted_at=:deleted_at WHERE owner_user_id=:owner_user_id AND id=:id AND status='active' RETURNING *"), {"owner_user_id": owner_user_id, "id": artifact_id, "deleted_at": deleted_at})).mappings().one_or_none()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _from_row(row) -> AgentArtifact:
        return AgentArtifact(**{field: row[field] for field in AgentArtifact.__dataclass_fields__})
