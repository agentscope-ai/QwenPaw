# -*- coding: utf-8 -*-
"""PostgreSQL 用量事实写入与匿名聚合。"""

from __future__ import annotations

import re
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..access.agent_repository import AgentResourceRole, agent_database_id
from ..persistence.database import database_session
from .manager import TokenUsageRecord

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _optional_uuid(value: str | UUID | None) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class UsageEvent:
    occurred_at: datetime
    user_id: UUID
    actor_type: str
    agent_key: str
    provider_key: str
    model_key: str
    prompt_tokens: int
    completion_tokens: int
    conversation_id: str | UUID | None = None
    run_id: str | UUID | None = None
    automation_schedule_id: str | UUID | None = None


class PostgresUsageRepository:
    """追加不可变用量事实，并只返回去身份化聚合。"""

    def __init__(
        self,
        *,
        schema: str,
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self.schema = normalized
        self._session_factory = session_factory

    def table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    async def append(self, event: UsageEvent) -> bool:
        """仅在全部必需归属元数据可解析时写入。"""
        if event.prompt_tokens < 0 or event.completion_tokens < 0:
            return False
        actor_type = (
            event.actor_type
            if event.actor_type
            in {
                "user",
                "external",
                "service",
                "automation",
            }
            else "user"
        )
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self.table('usage_records')} "
                    "(id,occurred_at,user_id,actor_type,agent_id,conversation_id,"
                    "run_id,automation_schedule_id,provider_id,model_id,"
                    "prompt_tokens,completion_tokens,call_count) "
                    "SELECT :id,:occurred_at,u.id,:actor_type,a.id,"
                    f"(SELECT id FROM {self.table('conversations')} WHERE id=:conversation_id),"
                    f"(SELECT id FROM {self.table('runs')} WHERE id=:run_id),"
                    f"(SELECT id FROM {self.table('automation_schedules')} WHERE id=:schedule_id),"
                    "p.id,m.id,:prompt_tokens,:completion_tokens,1 "
                    f"FROM {self.table('users')} u "
                    f"JOIN {self.table('agents')} a ON a.id=:agent_id "
                    f"JOIN {self.table('model_providers')} p ON p.name=:provider_key "
                    f"JOIN {self.table('models')} m ON m.provider_id=p.id "
                    "AND m.model_key=:model_key "
                    "WHERE u.id=:user_id AND u.status='active' "
                    "AND a.status<>'deleted' RETURNING id"
                ),
                {
                    "id": uuid4(),
                    "occurred_at": event.occurred_at,
                    "user_id": event.user_id,
                    "actor_type": actor_type,
                    "agent_id": agent_database_id(event.agent_key),
                    "provider_key": event.provider_key,
                    "model_key": event.model_key,
                    "conversation_id": _optional_uuid(event.conversation_id),
                    "run_id": _optional_uuid(event.run_id),
                    "schedule_id": _optional_uuid(event.automation_schedule_id),
                    "prompt_tokens": event.prompt_tokens,
                    "completion_tokens": event.completion_tokens,
                },
            )
            return result.scalar_one_or_none() is not None

    async def get_agent_role(
        self,
        *,
        user_id: UUID,
        agent_key: str,
    ) -> AgentResourceRole | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT CASE WHEN a.owner_user_id=:user_id THEN 'owner' "
                    "WHEN am.user_id IS NOT NULL THEN am.role "
                    "WHEN a.visibility='public' THEN 'user' END "
                    f"FROM {self.table('agents')} a "
                    f"LEFT JOIN {self.table('agent_members')} am "
                    "ON am.agent_id=a.id AND am.user_id=:user_id "
                    "AND am.revoked_at IS NULL "
                    "WHERE a.id=:agent_id AND a.status<>'deleted' "
                    "AND (a.owner_user_id=:user_id OR am.user_id IS NOT NULL "
                    "OR a.visibility='public')"
                ),
                {
                    "user_id": user_id,
                    "agent_id": agent_database_id(agent_key),
                },
            )
            role = result.scalar_one_or_none()
        return AgentResourceRole(role) if role else None

    async def get_details(
        self,
        *,
        start_date: date,
        end_date: date,
        user_id: UUID | None = None,
        agent_key: str | None = None,
        model_name: str | None = None,
        provider_key: str | None = None,
    ) -> list[TokenUsageRecord]:
        clauses = ["ur.occurred_at>=:started_at", "ur.occurred_at<:ended_at"]
        params: dict[str, object] = {
            "started_at": datetime.combine(start_date, time.min, tzinfo=UTC),
            "ended_at": datetime.combine(
                end_date + timedelta(days=1), time.min, tzinfo=UTC
            ),
        }
        if user_id is not None:
            clauses.append("ur.user_id=:user_id")
            params["user_id"] = user_id
        if agent_key is not None:
            clauses.append("ur.agent_id=:agent_id")
            params["agent_id"] = agent_database_id(agent_key)
        if model_name is not None:
            clauses.append("m.model_key=:model_name")
            params["model_name"] = model_name
        if provider_key is not None:
            clauses.append("p.name=:provider_key")
            params["provider_key"] = provider_key
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT to_char(ur.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD') "
                            "AS date,p.name AS provider_id,m.model_key AS model,"
                            "sum(ur.prompt_tokens) AS prompt_tokens,"
                            "sum(ur.completion_tokens) AS completion_tokens,"
                            "sum(ur.call_count) AS call_count "
                            f"FROM {self.table('usage_records')} ur "
                            f"JOIN {self.table('model_providers')} p ON p.id=ur.provider_id "
                            f"JOIN {self.table('models')} m ON m.id=ur.model_id "
                            f"WHERE {' AND '.join(clauses)} "
                            "GROUP BY 1,p.name,m.model_key ORDER BY 1,p.name,m.model_key"
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
        return [TokenUsageRecord.model_validate(dict(row)) for row in rows]


__all__ = ["PostgresUsageRepository", "UsageEvent"]
