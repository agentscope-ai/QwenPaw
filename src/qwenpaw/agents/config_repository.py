# -*- coding: utf-8 -*-
"""PostgreSQL-backed Agent structured configuration revisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..access.agent_repository import agent_database_id
from ..persistence.database import database_session

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class AgentConfigRevision:
    """当前 Agent 配置版本的不可变快照。"""

    agent_key: str
    version: int
    structured_config: dict[str, Any]
    content_hash: str
    changed_by: UUID | None
    created_at: datetime | None


class AgentConfigVersionConflict(RuntimeError):
    """提交者基于旧版本保存，不能覆盖较新的配置。"""

    def __init__(self, expected_version: int, current_version: int):
        super().__init__("agent_config_version_conflict")
        self.expected_version = expected_version
        self.current_version = current_version


def config_content_hash(structured_config: dict[str, Any]) -> str:
    """为结构化配置生成稳定、与字段顺序无关的 SHA-256 哈希。"""
    payload = json.dumps(
        structured_config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PostgresAgentConfigRepository:
    """保存 Agent 配置修订，不搬移 workspace 文件内容。"""

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
        self._agents_table = f"{prefix}agents"
        self._revisions_table = f"{prefix}agent_config_revisions"
        self._session_factory = session_factory
        self._clock = clock

    async def get_current(self, agent_key: str) -> AgentConfigRevision:
        agent_id = agent_database_id(agent_key)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT a.config_version, r.structured_config, "
                        "r.content_hash, r.changed_by, r.created_at "
                        f"FROM {self._agents_table} a "
                        f"LEFT JOIN {self._revisions_table} r "
                        "ON r.agent_id = a.id AND r.revision = a.config_version "
                        "WHERE a.id = :agent_id AND a.deleted_at IS NULL"
                    ),
                    {"agent_id": agent_id},
                )
            ).mappings().one_or_none()
        if row is None:
            raise KeyError(agent_key)
        config = dict(row["structured_config"] or {})
        return AgentConfigRevision(
            agent_key=agent_key,
            version=int(row["config_version"]),
            structured_config=config,
            content_hash=row["content_hash"] or config_content_hash(config),
            changed_by=row["changed_by"],
            created_at=row["created_at"],
        )

    async def save_revision(
        self,
        *,
        agent_key: str,
        expected_version: int,
        structured_config: dict[str, Any],
        changed_by: UUID,
    ) -> AgentConfigRevision:
        agent_id = agent_database_id(agent_key)
        content_hash = config_content_hash(structured_config)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT a.config_version, r.content_hash, "
                        "r.structured_config, r.changed_by, r.created_at "
                        f"FROM {self._agents_table} a "
                        f"LEFT JOIN {self._revisions_table} r "
                        "ON r.agent_id = a.id AND r.revision = a.config_version "
                        "WHERE a.id = :agent_id AND a.deleted_at IS NULL "
                        "FOR UPDATE OF a"
                    ),
                    {"agent_id": agent_id},
                )
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(agent_key)
            current_version = int(row["config_version"])
            if current_version != expected_version:
                raise AgentConfigVersionConflict(
                    expected_version,
                    current_version,
                )
            if row["content_hash"] == content_hash:
                return AgentConfigRevision(
                    agent_key=agent_key,
                    version=current_version,
                    structured_config=dict(
                        row["structured_config"] or structured_config
                    ),
                    content_hash=content_hash,
                    changed_by=row["changed_by"],
                    created_at=row["created_at"],
                )
            next_version = current_version + 1
            created_at = self._clock()
            await session.execute(
                text(
                    f"UPDATE {self._agents_table} "
                    "SET config_version = :version, updated_at = :updated_at "
                    "WHERE id = :agent_id"
                ),
                {
                    "version": next_version,
                    "updated_at": created_at,
                    "agent_id": agent_id,
                },
            )
            await session.execute(
                text(
                    f"INSERT INTO {self._revisions_table} "
                    "(id, agent_id, revision, structured_config, content_hash, "
                    "changed_by, created_at) VALUES "
                    "(gen_random_uuid(), :agent_id, :revision, "
                    "CAST(:structured_config AS jsonb), :content_hash, "
                    ":changed_by, :created_at)"
                ),
                {
                    "agent_id": agent_id,
                    "revision": next_version,
                    "structured_config": json.dumps(
                        structured_config,
                        ensure_ascii=False,
                    ),
                    "content_hash": content_hash,
                    "changed_by": changed_by,
                    "created_at": created_at,
                },
            )
        return AgentConfigRevision(
            agent_key=agent_key,
            version=next_version,
            structured_config=dict(structured_config),
            content_hash=content_hash,
            changed_by=changed_by,
            created_at=created_at,
        )
