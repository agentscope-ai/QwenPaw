# -*- coding: utf-8 -*-
"""用户账户操作的脱敏审计写入。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..access.actor import ActorContext
from ..persistence.database import database_session

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class UserAuditRepository:
    """仅记录操作者、目标、动作和发生变更的字段名。"""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self._table = f'"{normalized}".audit_logs'
        self._session_factory = session_factory

    async def record(
        self,
        *,
        actor: ActorContext,
        target_user_id: UUID,
        action: str,
        changed_fields: list[str],
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self._table} "
                    "(id, actor_user_id, actor_identity_type, action, "
                    "resource_type, resource_id, result, request_id, source, "
                    "redacted_detail) VALUES (:id, :actor_user_id, :actor_type, "
                    ":action, 'user', :resource_id, 'success', :request_id, "
                    "'web', CAST(:detail AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "actor_user_id": actor.user_id,
                    "actor_type": actor.actor_type.value,
                    "action": action,
                    "resource_id": target_user_id,
                    "request_id": actor.request_id,
                    "detail": json.dumps({"changed_fields": changed_fields}),
                },
            )
