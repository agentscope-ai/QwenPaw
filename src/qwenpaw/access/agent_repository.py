# -*- coding: utf-8 -*-
"""Agent 文件目录与 PostgreSQL 归属元数据 Repository。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_AGENT_ID_NAMESPACE = UUID("fe80bb92-fbd0-55be-b67c-4bbf27184d91")

AgentStatus = Literal["draft", "active", "disabled", "deleted"]


class AgentVisibility(StrEnum):
    """Agent 在多用户目录中的可见范围。"""

    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC_CANDIDATE = "public_candidate"
    PUBLIC = "public"


class AgentResourceRole(StrEnum):
    """用户在单个 Agent 上的资源角色。"""

    OWNER = "owner"
    COLLABORATOR = "collaborator"
    USER = "user"


@dataclass(frozen=True, slots=True)
class LegacyAgentRecord:
    """仍由现有文件配置提供的 Agent 展示和运行事实。"""

    key: str
    name: str
    description: str
    workspace_key: str
    status: AgentStatus


@dataclass(frozen=True, slots=True)
class AgentAccessRecord:
    """PostgreSQL 返回的 Agent 归属和当前用户角色。"""

    agent_key: str
    owner_user_id: UUID
    role: AgentResourceRole
    status: AgentStatus
    visibility: AgentVisibility = AgentVisibility.PRIVATE
    historical_read_only: bool = False


@dataclass(frozen=True, slots=True)
class AgentGovernanceRecord:
    """管理员治理列表和成员服务使用的 Agent 元数据。"""

    agent_key: str
    owner_user_id: UUID
    visibility: AgentVisibility
    status: AgentStatus


@dataclass(frozen=True, slots=True)
class AgentMemberRecord:
    """一个尚未撤销的 Agent 成员。"""

    user_id: UUID
    username: str
    role: AgentResourceRole


@dataclass(frozen=True, slots=True)
class AgentReferenceCounts:
    """软删除前需要保留的关联资源计数。"""

    conversations: int = 0
    skills: int = 0
    drivers: int = 0
    channels: int = 0
    automations: int = 0
    shared_apps: int = 0
    plugins: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "conversations": self.conversations,
            "skills": self.skills,
            "drivers": self.drivers,
            "channels": self.channels,
            "automations": self.automations,
            "shared_apps": self.shared_apps,
            "plugins": self.plugins,
        }


class AgentRegistrationConflict(RuntimeError):
    """同一文件 Agent 已被登记给其他用户。"""

    def __init__(self) -> None:
        super().__init__("agent_registration_conflict")


class AgentMetadataRepository(Protocol):
    """Agent 归属服务所需的最小持久化接口。"""

    async def get_first_admin_id(self) -> UUID | None: ...

    async def list_registered_keys(self, agent_keys: list[str]) -> set[str]: ...

    async def list_accessible(
        self,
        *,
        agent_keys: list[str],
        user_id: UUID,
    ) -> dict[str, AgentAccessRecord]: ...


class LegacyAgentRepository:
    """只读适配现有文件 Agent 目录，不写入归属事实。"""

    def __init__(self, loader: Callable[[], list[LegacyAgentRecord]]) -> None:
        self._loader = loader

    def list_agents(self) -> list[LegacyAgentRecord]:
        return list(self._loader())


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def agent_database_id(agent_key: str) -> UUID:
    """把稳定的文件 Agent ID 映射为既有 UUID 主键。"""
    return uuid5(_AGENT_ID_NAMESPACE, agent_key)


class PostgresAgentRepository:
    """保存 owner、成员关系和软删除状态，不搬移 workspace 内容。"""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        normalized_schema = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized_schema):
            raise ValueError("invalid_database_schema")
        prefix = f'"{normalized_schema}".'
        self._users_table = f"{prefix}users"
        self._agents_table = f"{prefix}agents"
        self._members_table = f"{prefix}agent_members"
        self._history_access_table = f"{prefix}agent_history_access"
        self._audit_table = f"{prefix}audit_logs"
        self._tables = {
            "conversations": f"{prefix}conversations",
            "skills": f"{prefix}agent_skills",
            "drivers": f"{prefix}agent_drivers",
            "channels": f"{prefix}channel_bindings",
            "automations": f"{prefix}automation_schedules",
            "shared_apps": f"{prefix}shared_apps",
            "plugins": f"{prefix}agent_plugin_settings",
        }
        self._session_factory = session_factory
        self._clock = clock

    async def get_first_admin_id(self) -> UUID | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id FROM "
                    f"{self._users_table} "
                    "WHERE platform_role = 'admin' AND status = 'active' "
                    "ORDER BY created_at, id LIMIT 1"
                )
            )
            return result.scalar_one_or_none()

    async def list_registered_keys(self, agent_keys: list[str]) -> set[str]:
        if not agent_keys:
            return set()
        key_by_id = {agent_database_id(key): key for key in agent_keys}
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT id FROM {self._agents_table} "
                    "WHERE id = ANY(CAST(:agent_ids AS uuid[]))"
                ),
                {"agent_ids": list(key_by_id)},
            )
            return {key_by_id[row[0]] for row in result.all() if row[0] in key_by_id}

    async def list_accessible(
        self,
        *,
        agent_keys: list[str],
        user_id: UUID,
    ) -> dict[str, AgentAccessRecord]:
        if not agent_keys:
            return {}
        key_by_id = {agent_database_id(key): key for key in agent_keys}
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT a.id, a.owner_user_id, a.status, a.visibility, "
                    "CASE WHEN a.owner_user_id = :user_id THEN 'owner' "
                    "WHEN am.user_id IS NOT NULL THEN am.role "
                    "WHEN a.visibility = 'public' THEN 'user' END AS access_role "
                    f"FROM {self._agents_table} a "
                    f"LEFT JOIN {self._members_table} am "
                    "ON am.agent_id = a.id AND am.user_id = :user_id "
                    "AND am.revoked_at IS NULL "
                    "WHERE a.id = ANY(CAST(:agent_ids AS uuid[])) "
                    "AND a.status <> 'deleted' "
                    "AND (a.owner_user_id = :user_id OR am.user_id IS NOT NULL "
                    "OR a.visibility = 'public')"
                ),
                {"agent_ids": list(key_by_id), "user_id": user_id},
            )
            rows = result.mappings().all()
        return {
            key_by_id[row["id"]]: AgentAccessRecord(
                agent_key=key_by_id[row["id"]],
                owner_user_id=row["owner_user_id"],
                role=AgentResourceRole(row["access_role"]),
                status=row["status"],
                visibility=AgentVisibility(row["visibility"]),
            )
            for row in rows
            if row["id"] in key_by_id
        }

    async def get_accessible(
        self,
        *,
        agent_key: str,
        user_id: UUID,
    ) -> AgentAccessRecord | None:
        records = await self.list_accessible(
            agent_keys=[agent_key],
            user_id=user_id,
        )
        return records.get(agent_key)

    async def list_historical_accessible(
        self,
        *,
        agent_keys: list[str],
        user_id: UUID,
    ) -> dict[str, AgentAccessRecord]:
        """返回仅因本人已有会话而保留的只读 Agent。"""
        if not agent_keys:
            return {}
        key_by_id = {agent_database_id(key): key for key in agent_keys}
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT a.id, a.owner_user_id, a.status, a.visibility "
                    f"FROM {self._agents_table} a "
                    f"JOIN {self._history_access_table} ah "
                    "ON ah.agent_id = a.id AND ah.user_id = :user_id "
                    f"LEFT JOIN {self._members_table} am "
                    "ON am.agent_id = a.id AND am.user_id = :user_id "
                    "AND am.revoked_at IS NULL "
                    "WHERE a.id = ANY(CAST(:agent_ids AS uuid[])) "
                    "AND a.status <> 'deleted' "
                    "AND a.owner_user_id <> :user_id "
                    "AND am.user_id IS NULL AND a.visibility <> 'public'"
                ),
                {"agent_ids": list(key_by_id), "user_id": user_id},
            )
            rows = result.mappings().all()
        return {
            key_by_id[row["id"]]: AgentAccessRecord(
                agent_key=key_by_id[row["id"]],
                owner_user_id=row["owner_user_id"],
                role=AgentResourceRole.USER,
                status=row["status"],
                visibility=AgentVisibility(row["visibility"]),
                historical_read_only=True,
            )
            for row in rows
            if row["id"] in key_by_id
        }

    async def record_chat_created(
        self,
        *,
        agent_key: str,
        user_id: UUID,
        created_at: datetime | None = None,
    ) -> None:
        """幂等记录用户已经在 Agent 下创建过持久化会话。"""
        timestamp = created_at or self._clock()
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self._history_access_table} "
                    "(agent_id, user_id, first_chat_created_at, "
                    "last_chat_created_at) "
                    "SELECT a.id, u.id, :created_at, :created_at "
                    f"FROM {self._agents_table} a "
                    f"JOIN {self._users_table} u ON u.id = :user_id "
                    "WHERE a.id = :agent_id AND a.status <> 'deleted' "
                    "ON CONFLICT (agent_id, user_id) DO UPDATE SET "
                    "first_chat_created_at = LEAST("
                    f"{self._history_access_table}.first_chat_created_at, "
                    "EXCLUDED.first_chat_created_at), "
                    "last_chat_created_at = GREATEST("
                    f"{self._history_access_table}.last_chat_created_at, "
                    "EXCLUDED.last_chat_created_at)"
                ),
                {
                    "agent_id": agent_database_id(agent_key),
                    "user_id": user_id,
                    "created_at": timestamp,
                },
            )

    async def register_owner(
        self,
        *,
        agent: LegacyAgentRecord,
        owner_user_id: UUID,
        status: AgentStatus | None = None,
    ) -> AgentAccessRecord:
        effective_status = status or agent.status
        database_id = agent_database_id(agent.key)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self._agents_table} "
                    "(id, owner_user_id, name, description, status, visibility, "
                    "default_model_mode, draft_workspace_key) "
                    "VALUES (:id, :owner_user_id, :name, :description, :status, "
                    "'private', 'inherited', :workspace_key) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "name = EXCLUDED.name, description = EXCLUDED.description, "
                    "status = EXCLUDED.status, draft_workspace_key = EXCLUDED.draft_workspace_key, "
                    "deleted_at = NULL, updated_at = now() "
                    f"WHERE {self._agents_table}.owner_user_id = EXCLUDED.owner_user_id "
                    f"AND {self._agents_table}.status IN ('draft', 'deleted') "
                    "RETURNING owner_user_id, status"
                ),
                {
                    "id": database_id,
                    "owner_user_id": owner_user_id,
                    "name": agent.name,
                    "description": agent.description,
                    "status": effective_status,
                    "workspace_key": agent.workspace_key,
                },
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise AgentRegistrationConflict()
        return AgentAccessRecord(
            agent_key=agent.key,
            owner_user_id=row["owner_user_id"],
            role=AgentResourceRole.OWNER,
            status=row["status"],
            visibility=AgentVisibility.PRIVATE,
        )

    async def get_governance(
        self,
        agent_key: str,
    ) -> AgentGovernanceRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT owner_user_id, visibility, status "
                    f"FROM {self._agents_table} WHERE id = :id"
                ),
                {"id": agent_database_id(agent_key)},
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        return AgentGovernanceRecord(
            agent_key=agent_key,
            owner_user_id=row["owner_user_id"],
            visibility=AgentVisibility(row["visibility"]),
            status=row["status"],
        )

    async def list_all_governance(
        self,
        agent_keys: list[str],
    ) -> list[AgentGovernanceRecord]:
        if not agent_keys:
            return []
        key_by_id = {agent_database_id(key): key for key in agent_keys}
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, owner_user_id, visibility, status "
                    f"FROM {self._agents_table} "
                    "WHERE id = ANY(CAST(:agent_ids AS uuid[])) "
                    "AND status <> 'deleted' ORDER BY created_at, id"
                ),
                {"agent_ids": list(key_by_id)},
            )
            rows = result.mappings().all()
        return [
            AgentGovernanceRecord(
                agent_key=key_by_id[row["id"]],
                owner_user_id=row["owner_user_id"],
                visibility=AgentVisibility(row["visibility"]),
                status=row["status"],
            )
            for row in rows
            if row["id"] in key_by_id
        ]

    async def list_members(self, agent_key: str) -> list[AgentMemberRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT am.user_id, u.username, am.role "
                    f"FROM {self._members_table} am "
                    f"JOIN {self._users_table} u ON u.id = am.user_id "
                    "WHERE am.agent_id = :agent_id AND am.revoked_at IS NULL "
                    "ORDER BY u.username, am.user_id"
                ),
                {"agent_id": agent_database_id(agent_key)},
            )
            rows = result.mappings().all()
        return [
            AgentMemberRecord(
                user_id=row["user_id"],
                username=row["username"],
                role=AgentResourceRole(row["role"]),
            )
            for row in rows
        ]

    async def grant_member(
        self,
        *,
        agent_key: str,
        user_id: UUID,
        role: AgentResourceRole,
        actor,
    ) -> None:
        agent_id = agent_database_id(agent_key)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self._members_table} "
                    "(agent_id, user_id, role, granted_by) "
                    f"SELECT :agent_id, u.id, :role, :actor_id FROM {self._users_table} u "
                    f"JOIN {self._agents_table} a ON a.id = :agent_id "
                    "WHERE u.id = :user_id AND u.status = 'active' "
                    "AND u.id <> a.owner_user_id "
                    "ON CONFLICT (agent_id, user_id) DO UPDATE SET "
                    "role = EXCLUDED.role, granted_by = EXCLUDED.granted_by, "
                    "created_at = now(), revoked_at = NULL RETURNING user_id"
                ),
                {
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "role": role.value,
                    "actor_id": actor.user_id,
                },
            )
            if result.scalar_one_or_none() is None:
                raise ValueError("member_user_not_available")
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} SET visibility = 'shared', "
                    "updated_at = now() WHERE id = :agent_id "
                    "AND visibility <> 'public'"
                ),
                {"agent_id": agent_id},
            )
            await self._write_audit(
                session,
                actor=actor,
                action="agent.member.grant",
                agent_id=agent_id,
                detail={"user_id": str(user_id), "role": role.value},
            )

    async def revoke_member(
        self,
        *,
        agent_key: str,
        user_id: UUID,
        actor,
    ) -> None:
        agent_id = agent_database_id(agent_key)
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"UPDATE {self._members_table} SET revoked_at = now() "
                    "WHERE agent_id = :agent_id AND user_id = :user_id "
                    "AND revoked_at IS NULL"
                ),
                {"agent_id": agent_id, "user_id": user_id},
            )
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} a SET visibility = 'private', "
                    "updated_at = now() WHERE a.id = :agent_id "
                    "AND a.visibility = 'shared' AND NOT EXISTS ("
                    f"SELECT 1 FROM {self._members_table} am "
                    "WHERE am.agent_id = a.id AND am.revoked_at IS NULL)"
                ),
                {"agent_id": agent_id},
            )
            await self._write_audit(
                session,
                actor=actor,
                action="agent.member.revoke",
                agent_id=agent_id,
                detail={"user_id": str(user_id)},
            )

    async def transfer_owner(
        self,
        *,
        agent_key: str,
        new_owner_user_id: UUID,
        actor,
    ) -> None:
        agent_id = agent_database_id(agent_key)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT a.owner_user_id FROM "
                    f"{self._agents_table} a JOIN {self._users_table} u "
                    "ON u.id = :new_owner_id AND u.status = 'active' "
                    "WHERE a.id = :agent_id AND a.owner_user_id = :actor_id "
                    "FOR UPDATE OF a"
                ),
                {
                    "agent_id": agent_id,
                    "new_owner_id": new_owner_user_id,
                    "actor_id": actor.user_id,
                },
            )
            previous_owner_id = result.scalar_one_or_none()
            if previous_owner_id is None:
                raise ValueError("owner_transfer_not_available")
            await session.execute(
                text(
                    f"DELETE FROM {self._members_table} "
                    "WHERE agent_id = :agent_id AND user_id = :new_owner_id"
                ),
                {"agent_id": agent_id, "new_owner_id": new_owner_user_id},
            )
            await session.execute(
                text(
                    f"INSERT INTO {self._members_table} "
                    "(agent_id, user_id, role, granted_by) "
                    "VALUES (:agent_id, :previous_owner_id, 'collaborator', :actor_id) "
                    "ON CONFLICT (agent_id, user_id) DO UPDATE SET "
                    "role = 'collaborator', granted_by = EXCLUDED.granted_by, "
                    "created_at = now(), revoked_at = NULL"
                ),
                {
                    "agent_id": agent_id,
                    "previous_owner_id": previous_owner_id,
                    "actor_id": actor.user_id,
                },
            )
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} SET owner_user_id = :new_owner_id, "
                    "visibility = CASE WHEN visibility = 'public' THEN 'public' "
                    "ELSE 'shared' END, updated_at = now() WHERE id = :agent_id"
                ),
                {"agent_id": agent_id, "new_owner_id": new_owner_user_id},
            )
            await self._write_audit(
                session,
                actor=actor,
                action="agent.owner.transfer",
                agent_id=agent_id,
                detail={"new_owner_user_id": str(new_owner_user_id)},
            )

    async def set_publication(
        self,
        *,
        agent_key: str,
        published: bool,
        actor,
    ) -> None:
        agent_id = agent_database_id(agent_key)
        async with self._session_factory() as session:
            visibility_sql = (
                "'public'"
                if published
                else (
                    "CASE WHEN EXISTS (SELECT 1 FROM "
                    f"{self._members_table} am WHERE am.agent_id = :agent_id "
                    "AND am.revoked_at IS NULL) THEN 'shared' ELSE 'private' END"
                )
            )
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} SET visibility = {visibility_sql}, "
                    "updated_at = now() WHERE id = :agent_id AND status <> 'deleted'"
                ),
                {"agent_id": agent_id},
            )
            await self._write_audit(
                session,
                actor=actor,
                action=("agent.publication.publish" if published else "agent.publication.revoke"),
                agent_id=agent_id,
                detail={"published": published},
            )

    async def record_admin_action(
        self,
        *,
        agent_key: str,
        action: str,
        actor,
    ) -> None:
        async with self._session_factory() as session:
            await self._write_audit(
                session,
                actor=actor,
                action=action,
                agent_id=agent_database_id(agent_key),
                detail={"admin_governance": True},
            )

    async def _write_audit(
        self,
        session: AsyncSession,
        *,
        actor,
        action: str,
        agent_id: UUID,
        detail: dict[str, object],
    ) -> None:
        await session.execute(
            text(
                f"INSERT INTO {self._audit_table} "
                "(id, actor_user_id, actor_identity_type, action, resource_type, "
                "resource_id, result, request_id, source, redacted_detail) "
                "VALUES (:id, :actor_user_id, :actor_identity_type, "
                ":action, 'agent', :resource_id, 'success', :request_id, "
                "'web', CAST(:detail AS jsonb))"
            ),
            {
                "id": uuid4(),
                "actor_user_id": actor.user_id,
                "actor_identity_type": actor.actor_type.value,
                "action": action,
                "resource_id": agent_id,
                "request_id": actor.request_id,
                "detail": json.dumps(detail),
            },
        )

    async def update_metadata(
        self,
        *,
        agent: LegacyAgentRecord,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} SET name = :name, "
                    "description = :description, status = :status, "
                    "draft_workspace_key = :workspace_key, updated_at = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": agent_database_id(agent.key),
                    "name": agent.name,
                    "description": agent.description,
                    "status": agent.status,
                    "workspace_key": agent.workspace_key,
                },
            )

    async def update_model_mode(
        self,
        agent_key: str,
        mode: Literal["inherited", "explicit"],
    ) -> bool:
        """同步 Agent 模型治理摘要，不修改文件配置。"""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"UPDATE {self._agents_table} SET "
                    "default_model_mode = :mode, updated_at = now() "
                    "WHERE id = :id "
                    "AND default_model_mode IS DISTINCT FROM :mode"
                ),
                {
                    "id": agent_database_id(agent_key),
                    "mode": mode,
                },
            )
            return bool(result.rowcount)

    async def set_status(self, agent_key: str, status: AgentStatus) -> None:
        deleted_at = self._clock() if status == "deleted" else None
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} SET status = :status, "
                    "deleted_at = :deleted_at, updated_at = now() WHERE id = :id"
                ),
                {
                    "id": agent_database_id(agent_key),
                    "status": status,
                    "deleted_at": deleted_at,
                },
            )

    async def reference_counts(self, agent_key: str) -> AgentReferenceCounts:
        expressions = ", ".join(
            f"(SELECT count(*) FROM {table} WHERE agent_id = :agent_id) AS {name}"
            for name, table in self._tables.items()
        )
        async with self._session_factory() as session:
            result = await session.execute(
                text(f"SELECT {expressions}"),
                {"agent_id": agent_database_id(agent_key)},
            )
            row = result.mappings().one()
        return AgentReferenceCounts(**{name: int(row[name]) for name in self._tables})
