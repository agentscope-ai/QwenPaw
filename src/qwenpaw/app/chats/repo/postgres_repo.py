# -*- coding: utf-8 -*-
"""PostgreSQL implementation of the complete Conversation Repository contract."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncContextManager
from uuid import UUID

from sqlalchemy import text

from ....persistence.database import database_session
from ....persistence.database import set_request_user
from .conversation import (
    AttachmentRecord,
    ConversationRecord,
    ConversationRepository,
    ConversationAccessRecord,
    ConversationMemberRecord,
    ConversationShareEligibilityError,
    ConversationStatus,
    MessageRecord,
    RepositoryConflictError,
    RunEventRecord,
    RunRecord,
    RunStatus,
    ShareCandidate,
    ToolCallRecord,
)

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PostgresConversationRepository(ConversationRepository):
    """Map contract records to the existing ``0002_agent_conversation`` tables."""

    def __init__(
        self,
        *,
        schema: str,
        session_factory: Callable[[], AsyncContextManager[Any]] = database_session,
        request_user_id: UUID | None = None,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("Unsafe PostgreSQL schema name")
        self.schema = normalized
        self._session_factory = session_factory
        self.request_user_id = request_user_id

    def with_user(self, user_id: UUID) -> PostgresConversationRepository:
        """创建共享同一连接工厂的请求用户绑定视图。"""
        return PostgresConversationRepository(
            schema=self.schema,
            session_factory=self._session_factory,
            request_user_id=user_id,
        )

    async def bind_publication(
        self,
        conversation_id,
        *,
        expected_agent_id,
        shared_app_id,
        publication_id,
        updated_at,
    ):
        """在所有权约束下，把新会话原子绑定到指定应用版本。"""
        if self.request_user_id is None:
            raise ValueError("conversation_owner_required")
        async with self._session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"UPDATE {self._table('conversations')} SET "
                            "shared_app_id=:app,publication_id=:publication,"
                            "model_override_id=NULL,updated_at=:updated "
                            "WHERE id=:id AND agent_id=:agent AND owner_user_id=:owner "
                            "AND shared_app_id IS NULL AND publication_id IS NULL "
                            "AND status<>'deleted' RETURNING *"
                        ),
                        {
                            "app": shared_app_id,
                            "publication": publication_id,
                            "updated": updated_at,
                            "id": conversation_id,
                            "agent": expected_agent_id,
                            "owner": self.request_user_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                return self._row(row, ConversationRecord)
            existing = (
                (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self._table('conversations')} "
                            "WHERE id=:id AND agent_id=:agent AND owner_user_id=:owner"
                        ),
                        {
                            "id": conversation_id,
                            "agent": expected_agent_id,
                            "owner": self.request_user_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                return None
            current = self._row(existing, ConversationRecord)
            if (
                current.shared_app_id == shared_app_id
                and current.publication_id == publication_id
            ):
                return current
            raise RepositoryConflictError("conversation_publication_conflict")

    async def set_model_override(
        self, conversation_id, *, expected_agent_id, model_override_id, updated_at
    ):
        if self.request_user_id is None:
            raise ValueError("conversation_owner_required")
        async with self._session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"UPDATE {self._table('conversations')} SET model_override_id=:model,updated_at=:updated "
                            "WHERE id=:id AND agent_id=:agent AND owner_user_id=:owner "
                            "AND publication_id IS NULL AND status<>'deleted' RETURNING *"
                        ),
                        {
                            "model": model_override_id,
                            "updated": updated_at,
                            "id": conversation_id,
                            "agent": expected_agent_id,
                            "owner": self.request_user_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            return self._row(row, ConversationRecord) if row else None

    @asynccontextmanager
    async def _session(self):
        async with self._session_factory() as session:
            if self.request_user_id is not None:
                await set_request_user(session, self.request_user_id)
            yield session

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    def _run_read_scope(self, conversation_alias: str = "c") -> tuple[str, dict]:
        """将 Run 及其子资源绑定到当前请求用户的会话访问范围。"""
        if self.request_user_id is None:
            return "", {}
        scope = (
            f" AND {conversation_alias}.status <> 'deleted' "
            "AND a.status <> 'deleted' AND ("
            f"{conversation_alias}.owner_user_id = :request_user_id OR ("
            f"EXISTS (SELECT 1 FROM {self._table('conversation_members')} cm "
            f"WHERE cm.conversation_id = {conversation_alias}.id "
            "AND cm.user_id = :request_user_id AND cm.role = 'viewer') "
            "AND (a.owner_user_id = :request_user_id OR a.visibility = 'public' "
            f"OR EXISTS (SELECT 1 FROM {self._table('agent_members')} am "
            "WHERE am.agent_id = a.id AND am.user_id = :request_user_id "
            "AND am.revoked_at IS NULL))))"
        )
        return scope, {"request_user_id": self.request_user_id}

    @staticmethod
    def _uuid(value: UUID | str) -> str:
        return str(value)

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _row(row: Any, model: type[Any]) -> Any:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        return model.model_validate(dict(mapping))

    async def create_conversation(
        self, record: ConversationRecord
    ) -> ConversationRecord:
        async with self._session() as session:
            existing = await session.execute(
                text(f"SELECT * FROM {self._table('conversations')} WHERE id=:id"),
                {"id": record.id},
            )
            row = existing.mappings().first()
            if row is not None:
                if self._row(row, ConversationRecord) != record:
                    raise RepositoryConflictError("conversation_conflict")
                return record
            await session.execute(
                text(
                    f"INSERT INTO {self._table('conversations')} "
                    "(id, agent_id, owner_user_id, title, status, model_override_id, "
                    "shared_app_id, publication_id, created_at, updated_at, deleted_at) VALUES "
                    "(:id,:agent_id,:owner_user_id,:title,:status,:model_override_id,"
                    ":shared_app_id,:publication_id,"
                    ":created_at,:updated_at,:deleted_at)"
                ),
                record.model_dump(),
            )
        return record

    async def get_conversation(
        self, conversation_id: UUID
    ) -> ConversationRecord | None:
        async with self._session() as session:
            result = await session.execute(
                text(f"SELECT * FROM {self._table('conversations')} WHERE id=:id"),
                {"id": conversation_id},
            )
            row = result.mappings().first()
        return self._row(row, ConversationRecord) if row else None

    async def list_conversations(
        self, *, owner_user_id: UUID, include_deleted: bool = False
    ) -> list[ConversationRecord]:
        deleted_clause = "" if include_deleted else " AND status <> 'deleted'"
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('conversations')} "
                    f"WHERE owner_user_id=:owner_user_id{deleted_clause} "
                    "ORDER BY updated_at DESC"
                ),
                {"owner_user_id": owner_user_id},
            )
            rows = result.mappings().all()
        return [self._row(row, ConversationRecord) for row in rows]

    async def list_conversations_for_user(
        self,
        *,
        user_id: UUID,
        scope: str = "all",
    ) -> list[ConversationAccessRecord]:
        if scope not in {"all", "owned", "shared"}:
            raise ValueError("invalid_conversation_scope")
        scope_clause = {
            "owned": "c.owner_user_id = :user_id",
            "shared": "cm.user_id = :user_id AND c.owner_user_id <> :user_id",
            "all": "(c.owner_user_id = :user_id OR cm.user_id = :user_id)",
        }[scope]
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT c.*, CASE WHEN c.owner_user_id = :user_id "
                    f"THEN 'owner' ELSE 'viewer' END AS access_role, "
                    f"CASE WHEN c.owner_user_id = :user_id THEN NULL "
                    f"ELSE granted.username END AS shared_by_username "
                    f"FROM {self._table('conversations')} c "
                    f"LEFT JOIN {self._table('conversation_members')} cm "
                    "ON cm.conversation_id = c.id AND cm.role = 'viewer' "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"LEFT JOIN {self._table('agent_members')} am "
                    "ON am.agent_id = a.id AND am.user_id = :user_id "
                    "AND am.revoked_at IS NULL "
                    f"LEFT JOIN {self._table('users')} granted "
                    "ON granted.id = cm.granted_by "
                    f"WHERE c.status <> 'deleted' AND a.status <> 'deleted' "
                    f"AND {scope_clause} "
                    "AND (c.owner_user_id = :user_id OR ("
                    "cm.user_id = :user_id AND (a.owner_user_id = :user_id "
                    "OR a.visibility = 'public' OR am.user_id IS NOT NULL))) "
                    "ORDER BY c.updated_at DESC"
                ),
                {"user_id": user_id},
            )
            rows = result.mappings().all()
        records: list[ConversationAccessRecord] = []
        seen: set[UUID] = set()
        for row in rows:
            conversation = self._row(row, ConversationRecord)
            if conversation.id in seen:
                continue
            seen.add(conversation.id)
            records.append(
                ConversationAccessRecord(
                    conversation=conversation,
                    access_role=row["access_role"],
                    shared_by_username=row["shared_by_username"],
                )
            )
        return records

    async def get_conversation_for_user(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
    ) -> ConversationAccessRecord | None:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT c.*, CASE WHEN c.owner_user_id = :user_id "
                    f"THEN 'owner' ELSE 'viewer' END AS access_role, "
                    f"CASE WHEN c.owner_user_id = :user_id THEN NULL "
                    f"ELSE granted.username END AS shared_by_username "
                    f"FROM {self._table('conversations')} c "
                    f"LEFT JOIN {self._table('conversation_members')} cm "
                    "ON cm.conversation_id = c.id AND cm.user_id = :user_id "
                    "AND cm.role = 'viewer' "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"LEFT JOIN {self._table('agent_members')} am "
                    "ON am.agent_id = a.id AND am.user_id = :user_id "
                    "AND am.revoked_at IS NULL "
                    f"LEFT JOIN {self._table('users')} granted "
                    "ON granted.id = cm.granted_by "
                    "WHERE c.id = :conversation_id AND c.status <> 'deleted' "
                    "AND a.status <> 'deleted' AND (c.owner_user_id = :user_id "
                    "OR (cm.user_id = :user_id AND (a.owner_user_id = :user_id "
                    "OR a.visibility = 'public' OR am.user_id IS NOT NULL)))"
                ),
                {"conversation_id": conversation_id, "user_id": user_id},
            )
            row = result.mappings().first()
        if row is None:
            return None
        return ConversationAccessRecord(
            conversation=self._row(row, ConversationRecord),
            access_role=row["access_role"],
            shared_by_username=row["shared_by_username"],
        )

    async def list_members(
        self,
        *,
        conversation_id: UUID,
        owner_user_id: UUID,
    ) -> list[ConversationMemberRecord]:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT cm.conversation_id, cm.user_id, u.username, "
                    "cm.role, cm.granted_by, cm.created_at "
                    f"FROM {self._table('conversation_members')} cm "
                    f"JOIN {self._table('conversations')} c "
                    "ON c.id = cm.conversation_id "
                    f"JOIN {self._table('users')} u ON u.id = cm.user_id "
                    "WHERE cm.conversation_id = :conversation_id "
                    "AND c.owner_user_id = :owner_user_id "
                    "ORDER BY u.username, cm.user_id"
                ),
                {
                    "conversation_id": conversation_id,
                    "owner_user_id": owner_user_id,
                },
            )
            rows = result.mappings().all()
        return [self._row(row, ConversationMemberRecord) for row in rows]

    async def list_share_candidates(
        self,
        *,
        conversation_id: UUID,
        owner_user_id: UUID,
    ) -> list[ShareCandidate]:
        async with self._session() as session:
            result = await session.execute(
                text(
                    "SELECT DISTINCT u.id AS user_id, u.username, u.platform_role "
                    f"FROM {self._table('conversations')} c "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"JOIN {self._table('users')} u ON u.status = 'active' "
                    f"LEFT JOIN {self._table('agent_members')} am "
                    "ON am.agent_id = a.id AND am.user_id = u.id "
                    "AND am.revoked_at IS NULL "
                    f"LEFT JOIN {self._table('conversation_members')} cm "
                    "ON cm.conversation_id = c.id AND cm.user_id = u.id "
                    "WHERE c.id = :conversation_id "
                    "AND c.owner_user_id = :owner_user_id "
                    "AND c.status <> 'deleted' AND a.status = 'active' "
                    "AND u.id <> c.owner_user_id AND cm.user_id IS NULL "
                    "AND (a.owner_user_id = u.id OR a.visibility = 'public' "
                    "OR am.user_id IS NOT NULL) "
                    "ORDER BY u.username, u.id"
                ),
                {
                    "conversation_id": conversation_id,
                    "owner_user_id": owner_user_id,
                },
            )
            rows = result.mappings().all()
        return [self._row(row, ShareCandidate) for row in rows]

    async def add_viewer(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        granted_by: UUID,
    ) -> ConversationMemberRecord:
        async with self._session() as session:
            existing = await session.execute(
                text(
                    "SELECT cm.conversation_id, cm.user_id, u.username, "
                    "cm.role, cm.granted_by, cm.created_at "
                    f"FROM {self._table('conversation_members')} cm "
                    f"JOIN {self._table('conversations')} c "
                    "ON c.id = cm.conversation_id "
                    f"JOIN {self._table('users')} u ON u.id = cm.user_id "
                    "WHERE cm.conversation_id = :conversation_id "
                    "AND cm.user_id = :user_id "
                    "AND c.owner_user_id = :granted_by"
                ),
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "granted_by": granted_by,
                },
            )
            row = existing.mappings().first()
            if row is not None:
                return self._row(row, ConversationMemberRecord)

            inserted = await session.execute(
                text(
                    f"INSERT INTO {self._table('conversation_members')} "
                    "(conversation_id, user_id, role, granted_by) "
                    "SELECT c.id, u.id, 'viewer', :granted_by "
                    f"FROM {self._table('conversations')} c "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"JOIN {self._table('users')} u "
                    "ON u.id = :user_id AND u.status = 'active' "
                    f"LEFT JOIN {self._table('agent_members')} am "
                    "ON am.agent_id = a.id AND am.user_id = u.id "
                    "AND am.revoked_at IS NULL "
                    "WHERE c.id = :conversation_id "
                    "AND c.owner_user_id = :granted_by "
                    "AND c.status <> 'deleted' AND a.status = 'active' "
                    "AND u.id <> c.owner_user_id "
                    "AND (a.owner_user_id = u.id OR a.visibility = 'public' "
                    "OR am.user_id IS NOT NULL) "
                    "ON CONFLICT (conversation_id, user_id) DO NOTHING "
                    "RETURNING conversation_id, user_id, role, granted_by, created_at"
                ),
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "granted_by": granted_by,
                },
            )
            inserted_row = inserted.mappings().first()
            if inserted_row is None:
                raise ConversationShareEligibilityError(
                    "conversation_share_candidate_unavailable"
                )
            user_result = await session.execute(
                text(f"SELECT username FROM {self._table('users')} WHERE id=:user_id"),
                {"user_id": user_id},
            )
            username = user_result.scalar_one()
        return ConversationMemberRecord(
            **dict(inserted_row),
            username=username,
        )

    async def remove_viewer(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        owner_user_id: UUID,
    ) -> bool:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"DELETE FROM {self._table('conversation_members')} cm "
                    f"USING {self._table('conversations')} c "
                    "WHERE cm.conversation_id = c.id "
                    "AND cm.conversation_id = :conversation_id "
                    "AND cm.user_id = :user_id "
                    "AND c.owner_user_id = :owner_user_id "
                    "RETURNING cm.user_id"
                ),
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "owner_user_id": owner_user_id,
                },
            )
            return result.scalar_one_or_none() is not None

    async def update_conversation(
        self,
        conversation_id: UUID,
        *,
        title: str | None = None,
        status: ConversationStatus | None = None,
        updated_at: datetime,
    ) -> ConversationRecord | None:
        current = await self.get_conversation(conversation_id)
        if current is None:
            return None
        updates: dict[str, Any] = {"updated_at": updated_at}
        if title is not None:
            updates["title"] = title
        if status is not None:
            updates["status"] = status
            if status == "deleted":
                updates["deleted_at"] = updated_at
        updated = current.model_copy(update=updates)
        async with self._session() as session:
            await session.execute(
                text(
                    f"UPDATE {self._table('conversations')} SET title=:title, "
                    "status=:status, updated_at=:updated_at, deleted_at=:deleted_at "
                    "WHERE id=:id"
                ),
                {
                    "id": conversation_id,
                    "title": updated.title,
                    "status": updated.status,
                    "updated_at": updated.updated_at,
                    "deleted_at": updated.deleted_at,
                },
            )
        return updated

    async def save_message(self, record: MessageRecord) -> MessageRecord:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('messages')} WHERE "
                    "conversation_id=:conversation_id AND sequence=:sequence"
                ),
                {
                    "conversation_id": record.conversation_id,
                    "sequence": record.sequence,
                },
            )
            row = result.mappings().first()
            if row is not None:
                if self._row(row, MessageRecord) != record:
                    raise RepositoryConflictError("message_sequence_conflict")
                return record
            values = record.model_dump()
            values["content"] = self._json(record.content)
            await session.execute(
                text(
                    f"INSERT INTO {self._table('messages')} "
                    "(id,conversation_id,run_id,sequence,role,message_type,content,status,"
                    "created_by,created_at) VALUES (:id,:conversation_id,:run_id,:sequence,"
                    ":role,:message_type,CAST(:content AS json),:status,:created_by,:created_at)"
                ),
                values,
            )
        return record

    async def list_messages(self, conversation_id: UUID) -> list[MessageRecord]:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('messages')} WHERE conversation_id=:id ORDER BY sequence"
                ),
                {"id": conversation_id},
            )
            rows = result.mappings().all()
        return [self._row(row, MessageRecord) for row in rows]

    async def create_run(self, record: RunRecord) -> RunRecord:
        async with self._session() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self._table('runs')} "
                    "(id,conversation_id,initiated_by,status,started_at,finished_at,error_summary) "
                    "VALUES (:id,:conversation_id,:initiated_by,:status,:started_at,:finished_at,:error_summary)"
                ),
                record.model_dump(),
            )
        return record

    async def get_run(self, run_id: UUID) -> RunRecord | None:
        scope, scope_params = self._run_read_scope()
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT r.* FROM {self._table('runs')} r "
                    f"JOIN {self._table('conversations')} c ON c.id = r.conversation_id "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"WHERE r.id=:id{scope}"
                ),
                {"id": run_id, **scope_params},
            )
            row = result.mappings().first()
        return self._row(row, RunRecord) if row else None

    async def finish_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        finished_at: datetime,
        error_summary: str | None = None,
    ) -> RunRecord | None:
        current = await self.get_run(run_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "status": status,
                "finished_at": finished_at,
                "error_summary": error_summary,
            }
        )
        async with self._session() as session:
            await session.execute(
                text(
                    f"UPDATE {self._table('runs')} SET status=:status, finished_at=:finished_at, error_summary=:error_summary WHERE id=:id"
                ),
                {
                    "id": run_id,
                    "status": status,
                    "finished_at": finished_at,
                    "error_summary": error_summary,
                },
            )
        return updated

    async def append_event(self, record: RunEventRecord) -> RunEventRecord:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('run_events')} WHERE run_id=:run_id AND sequence=:sequence"
                ),
                {"run_id": record.run_id, "sequence": record.sequence},
            )
            row = result.mappings().first()
            if row is not None:
                if self._row(row, RunEventRecord) != record:
                    raise RepositoryConflictError("run_event_sequence_conflict")
                return record
            values = record.model_dump()
            values["payload"] = self._json(record.payload)
            await session.execute(
                text(
                    f"INSERT INTO {self._table('run_events')} (id,run_id,sequence,event_type,payload,tool_call_id,created_at) VALUES (:id,:run_id,:sequence,:event_type,CAST(:payload AS json),:tool_call_id,:created_at)"
                ),
                values,
            )
        return record

    async def list_events(self, run_id: UUID) -> list[RunEventRecord]:
        scope, scope_params = self._run_read_scope()
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT e.* FROM {self._table('run_events')} e "
                    f"JOIN {self._table('runs')} r ON r.id = e.run_id "
                    f"JOIN {self._table('conversations')} c ON c.id = r.conversation_id "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"WHERE e.run_id=:id{scope} ORDER BY e.sequence"
                ),
                {"id": run_id, **scope_params},
            )
            rows = result.mappings().all()
        return [self._row(row, RunEventRecord) for row in rows]

    async def upsert_tool_call(self, record: ToolCallRecord) -> ToolCallRecord:
        values = record.model_dump()
        values["redacted_arguments"] = self._json(record.redacted_arguments)
        async with self._session() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self._table('tool_calls')} (id,run_id,call_id,source,tool_name,status,redacted_arguments,approval_id,output_ref,started_at,finished_at) VALUES (:id,:run_id,:call_id,:source,:tool_name,:status,CAST(:redacted_arguments AS json),:approval_id,:output_ref,:started_at,:finished_at) ON CONFLICT (run_id,call_id) DO UPDATE SET source=EXCLUDED.source, tool_name=EXCLUDED.tool_name, status=EXCLUDED.status, redacted_arguments=EXCLUDED.redacted_arguments, approval_id=EXCLUDED.approval_id, output_ref=EXCLUDED.output_ref, started_at=EXCLUDED.started_at, finished_at=EXCLUDED.finished_at"
                ),
                values,
            )
        return record

    async def list_tool_calls(self, run_id: UUID) -> list[ToolCallRecord]:
        scope, scope_params = self._run_read_scope()
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT tc.* FROM {self._table('tool_calls')} tc "
                    f"JOIN {self._table('runs')} r ON r.id = tc.run_id "
                    f"JOIN {self._table('conversations')} c ON c.id = r.conversation_id "
                    f"JOIN {self._table('agents')} a ON a.id = c.agent_id "
                    f"WHERE tc.run_id=:id{scope} "
                    "ORDER BY tc.started_at NULLS LAST, tc.id"
                ),
                {"id": run_id, **scope_params},
            )
            rows = result.mappings().all()
        return [self._row(row, ToolCallRecord) for row in rows]

    async def add_attachment(self, record: AttachmentRecord) -> AttachmentRecord:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('attachments')} WHERE storage_key=:storage_key"
                ),
                {"storage_key": record.storage_key},
            )
            row = result.mappings().first()
            if row is not None:
                if self._row(row, AttachmentRecord) != record:
                    raise RepositoryConflictError("attachment_conflict")
                return record
            await session.execute(
                text(
                    f"INSERT INTO {self._table('attachments')} "
                    "(id,agent_id,conversation_id,message_id,owner_user_id,"
                    "storage_key,original_name,media_type,size,content_hash,"
                    "created_at,lifecycle,saved_path,saved_at,deleted_at,updated_at) "
                    "VALUES (:id,:agent_id,:conversation_id,"
                    ":message_id,:owner_user_id,:storage_key,:original_name,"
                    ":media_type,:size,:content_hash,:created_at,:lifecycle,"
                    ":saved_path,:saved_at,:deleted_at,:updated_at)"
                ),
                record.model_dump(),
            )
        return record

    async def get_attachment(
        self,
        *,
        attachment_id: UUID,
        owner_user_id: UUID,
    ) -> AttachmentRecord | None:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('attachments')} "
                    "WHERE id=:id AND owner_user_id=:owner_user_id"
                ),
                {"id": attachment_id, "owner_user_id": owner_user_id},
            )
            row = result.mappings().first()
        return self._row(row, AttachmentRecord) if row else None

    async def bind_attachment(
        self,
        *,
        attachment_id: UUID,
        owner_user_id: UUID,
        agent_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
    ) -> AttachmentRecord:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('attachments')} "
                    "WHERE id=:id AND owner_user_id=:owner_user_id FOR UPDATE"
                ),
                {"id": attachment_id, "owner_user_id": owner_user_id},
            )
            row = result.mappings().first()
            if row is None:
                raise RepositoryConflictError("attachment_not_found")
            current = self._row(row, AttachmentRecord)
            if current.agent_id != agent_id:
                raise RepositoryConflictError("attachment_agent_mismatch")
            if current.conversation_id not in {None, conversation_id}:
                raise RepositoryConflictError("attachment_conversation_mismatch")
            if current.message_id not in {None, message_id}:
                raise RepositoryConflictError("attachment_message_mismatch")
            await session.execute(
                text(
                    f"UPDATE {self._table('attachments')} "
                    "SET conversation_id=:conversation_id, message_id=:message_id "
                    "WHERE id=:id AND owner_user_id=:owner_user_id"
                ),
                {
                    "id": attachment_id,
                    "owner_user_id": owner_user_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                },
            )
        return current.model_copy(
            update={
                "conversation_id": conversation_id,
                "message_id": message_id,
            }
        )

    async def list_attachments(self, conversation_id: UUID) -> list[AttachmentRecord]:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('attachments')} WHERE conversation_id=:id ORDER BY created_at, id"
                ),
                {"id": conversation_id},
            )
            rows = result.mappings().all()
        return [self._row(row, AttachmentRecord) for row in rows]

    async def list_owned_attachments(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        lifecycle=None,
        conversation_id: UUID | None = None,
    ) -> list[AttachmentRecord]:
        conditions = [
            "owner_user_id=:owner_user_id",
            "agent_id=:agent_id",
        ]
        values = {
            "owner_user_id": owner_user_id,
            "agent_id": agent_id,
        }
        if lifecycle is None:
            conditions.append("lifecycle <> 'deleted'")
        else:
            conditions.append("lifecycle=:lifecycle")
            values["lifecycle"] = lifecycle
        if conversation_id is not None:
            conditions.append("conversation_id=:conversation_id")
            values["conversation_id"] = conversation_id
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM {self._table('attachments')} WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY created_at, id"
                ),
                values,
            )
            rows = result.mappings().all()
        return [self._row(row, AttachmentRecord) for row in rows]

    async def update_attachment_lifecycle(
        self,
        *,
        attachment_id,
        owner_user_id,
        lifecycle,
        storage_key,
        saved_path,
        saved_at,
        deleted_at,
        updated_at,
    ):
        async with self._session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"UPDATE {self._table('attachments')} SET lifecycle=:lifecycle, storage_key=:storage_key, saved_path=:saved_path, saved_at=:saved_at, deleted_at=:deleted_at, updated_at=:updated_at WHERE id=:id AND owner_user_id=:owner_user_id RETURNING *"
                        ),
                        {
                            "id": attachment_id,
                            "owner_user_id": owner_user_id,
                            "lifecycle": lifecycle,
                            "storage_key": storage_key,
                            "saved_path": saved_path,
                            "saved_at": saved_at,
                            "deleted_at": deleted_at,
                            "updated_at": updated_at,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._row(row, AttachmentRecord) if row else None

    async def persist_frame(
        self,
        *,
        event: RunEventRecord,
        message: MessageRecord | None = None,
        tool_call: ToolCallRecord | None = None,
        attachments: list[AttachmentRecord] | None = None,
        terminal_status: RunStatus | None = None,
    ) -> None:
        """在单一事务中收敛一个 wire 帧产生的全部持久化事实。"""
        async with self._session() as session:
            if tool_call is not None:
                values = tool_call.model_dump()
                values["redacted_arguments"] = self._json(tool_call.redacted_arguments)
                approval_id = values["approval_id"]
                values["approval_id"] = None
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('tool_calls')} "
                        "(id,run_id,call_id,source,tool_name,status,"
                        "redacted_arguments,approval_id,output_ref,started_at,"
                        "finished_at) VALUES (:id,:run_id,:call_id,:source,"
                        ":tool_name,:status,CAST(:redacted_arguments AS json),"
                        ":approval_id,:output_ref,:started_at,:finished_at) "
                        "ON CONFLICT (run_id,call_id) DO UPDATE SET "
                        "source=EXCLUDED.source, tool_name=EXCLUDED.tool_name, "
                        "status=EXCLUDED.status, "
                        "redacted_arguments=EXCLUDED.redacted_arguments, "
                        "approval_id=EXCLUDED.approval_id, "
                        "output_ref=EXCLUDED.output_ref, "
                        "started_at=EXCLUDED.started_at, "
                        "finished_at=EXCLUDED.finished_at"
                    ),
                    values,
                )
                if approval_id is not None:
                    await session.execute(
                        text(
                            f"INSERT INTO {self._table('approval_requests')} "
                            "(id,approval_user_id,agent_id,conversation_id,run_id,"
                            "tool_call_id,capability,redacted_arguments,status) "
                            "SELECT :approval_id,r.initiated_by,c.agent_id,"
                            "r.conversation_id,r.id,:tool_call_id,:capability,"
                            "CAST(:redacted_arguments AS json),:status "
                            f"FROM {self._table('runs')} r JOIN "
                            f"{self._table('conversations')} c "
                            "ON c.id=r.conversation_id WHERE r.id=:run_id "
                            "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, "
                            "decided_at=CASE WHEN EXCLUDED.status NOT IN "
                            "('pending','running') THEN now() ELSE NULL END"
                        ),
                        {
                            "approval_id": approval_id,
                            "tool_call_id": tool_call.id,
                            "capability": tool_call.tool_name,
                            "redacted_arguments": values["redacted_arguments"],
                            "status": tool_call.status,
                            "run_id": tool_call.run_id,
                        },
                    )
                    await session.execute(
                        text(
                            f"UPDATE {self._table('tool_calls')} "
                            "SET approval_id=:approval_id WHERE id=:tool_call_id"
                        ),
                        {
                            "approval_id": approval_id,
                            "tool_call_id": tool_call.id,
                        },
                    )
            if message is not None:
                values = message.model_dump()
                values["content"] = self._json(message.content)
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('messages')} "
                        "(id,conversation_id,run_id,sequence,role,message_type,"
                        "content,status,created_by,created_at) VALUES "
                        "(:id,:conversation_id,:run_id,:sequence,:role,"
                        ":message_type,CAST(:content AS json),:status,"
                        ":created_by,:created_at) ON CONFLICT (id) DO UPDATE "
                        "SET role=EXCLUDED.role, message_type=EXCLUDED.message_type, "
                        "content=EXCLUDED.content, status=EXCLUDED.status"
                    ),
                    values,
                )
            event_values = event.model_dump()
            event_values["payload"] = self._json(event.payload)
            await session.execute(
                text(
                    f"INSERT INTO {self._table('run_events')} "
                    "(id,run_id,sequence,event_type,payload,tool_call_id,created_at) "
                    "VALUES (:id,:run_id,:sequence,:event_type,"
                    "CAST(:payload AS json),:tool_call_id,:created_at) "
                    "ON CONFLICT (run_id,sequence) DO NOTHING"
                ),
                event_values,
            )
            for attachment in attachments or []:
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('attachments')} "
                        "(id,agent_id,conversation_id,message_id,owner_user_id,"
                        "storage_key,original_name,media_type,size,content_hash,"
                        "created_at,lifecycle,saved_path,saved_at,deleted_at,updated_at) VALUES "
                        "(:id,:agent_id,:conversation_id,:message_id,"
                        ":owner_user_id,:storage_key,:original_name,:media_type,"
                        ":size,:content_hash,:created_at,:lifecycle,:saved_path,"
                        ":saved_at,:deleted_at,:updated_at) "
                        "ON CONFLICT (storage_key) DO NOTHING"
                    ),
                    attachment.model_dump(),
                )
            if terminal_status is not None:
                await session.execute(
                    text(
                        f"UPDATE {self._table('runs')} SET status=:status, "
                        "finished_at=:finished_at WHERE id=:run_id"
                    ),
                    {
                        "run_id": event.run_id,
                        "status": terminal_status,
                        "finished_at": event.created_at,
                    },
                )
