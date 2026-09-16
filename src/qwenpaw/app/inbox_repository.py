# -*- coding: utf-8 -*-
"""多用户私人收件箱 PostgreSQL Repository。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _optional_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _payload_ref(
    *,
    agent_id: str | None,
    source_id: str | None,
    payload: dict[str, Any] | None,
) -> str:
    return json.dumps(
        {
            "agent_id": agent_id or "default",
            "source_id": source_id or "",
            "payload": payload or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_payload_ref(raw: Any) -> tuple[str, str, dict[str, Any]]:
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw else {}
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    payload = value.get("payload")
    return (
        str(value.get("agent_id") or "default"),
        str(value.get("source_id") or ""),
        payload if isinstance(payload, dict) else {},
    )


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0


def _event_from_row(row: Any) -> dict[str, Any]:
    agent_id, source_id, payload = _decode_payload_ref(row["payload_ref"])
    return {
        "id": str(row["id"]),
        "agent_id": agent_id,
        "source_type": row["source_type"],
        "source_id": source_id,
        "event_type": row["event_type"],
        "status": row["status"],
        "severity": row["severity"],
        "title": row["title"],
        "body": row["body"] or "",
        "payload": payload,
        "recipient_user_id": str(row["recipient_user_id"]),
        "read": row["read_at"] is not None,
        "created_at": _timestamp(row["created_at"]),
    }


class PostgresInboxRepository:
    """将通知事实与用户回执分开保存。"""

    def __init__(
        self,
        *,
        schema: str,
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self._notifications = f'"{normalized}".notifications'
        self._receipts = f'"{normalized}".notification_receipts'
        self._session_factory = session_factory

    async def append_event(
        self,
        *,
        recipient_user_id: UUID,
        agent_id: str | None,
        source_type: str,
        source_id: str | None,
        event_type: str,
        status: str,
        severity: str,
        title: str,
        body: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        notification_id = uuid4()
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self._notifications} "
                    "(id,recipient_user_id,agent_id,source_type,source_id,"
                    "event_type,status,severity,title,body,payload_ref) "
                    "VALUES (:id,:recipient_user_id,NULL,:source_type,:source_id,"
                    ":event_type,:status,:severity,:title,:body,:payload_ref) "
                    "RETURNING id,recipient_user_id,source_type,event_type,status,"
                    "severity,title,body,payload_ref,created_at"
                ),
                {
                    "id": notification_id,
                    "recipient_user_id": recipient_user_id,
                    "source_type": source_type,
                    "source_id": _optional_uuid(source_id),
                    "event_type": event_type,
                    "status": status,
                    "severity": severity,
                    "title": title,
                    "body": body,
                    "payload_ref": _payload_ref(
                        agent_id=agent_id,
                        source_id=source_id,
                        payload=payload,
                    ),
                },
            )
            row = result.mappings().one()
            await session.execute(
                text(
                    f"INSERT INTO {self._receipts} "
                    "(notification_id,user_id,read_at,deleted_at) "
                    "VALUES (:notification_id,:user_id,NULL,NULL)"
                ),
                {"notification_id": notification_id, "user_id": recipient_user_id},
            )
        return _event_from_row({**row, "read_at": None})

    def _filters(
        self,
        *,
        source_types: set[str] | None,
        status: str | None,
        agent_id: str | None,
        unread_only: bool,
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["n.recipient_user_id = :recipient_user_id", "r.deleted_at IS NULL"]
        params: dict[str, Any] = {}
        if source_types:
            clauses.append("n.source_type IN :source_types")
            params["source_types"] = sorted(source_types)
        if status:
            clauses.append("n.status = :status")
            params["status"] = status
        if agent_id:
            clauses.append("(CAST(n.payload_ref AS jsonb)->>'agent_id') = :agent_id")
            params["agent_id"] = agent_id
        if unread_only:
            clauses.append("r.read_at IS NULL")
        return " AND ".join(clauses), params

    async def query_events(
        self,
        *,
        recipient_user_id: UUID,
        limit: int,
        offset: int,
        source_types: set[str] | None = None,
        status: str | None = None,
        agent_id: str | None = None,
        unread_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int, int]:
        where, params = self._filters(
            source_types=source_types,
            status=status,
            agent_id=agent_id,
            unread_only=unread_only,
        )
        params.update(
            recipient_user_id=recipient_user_id,
            limit=max(limit, 0),
            offset=max(offset, 0),
        )
        statement = text(
            f"SELECT n.id,n.recipient_user_id,n.source_type,n.event_type,"
            "n.status,n.severity,n.title,n.body,n.payload_ref,n.created_at,"
            f"r.read_at FROM {self._notifications} n JOIN {self._receipts} r "
            "ON r.notification_id=n.id AND r.user_id=:recipient_user_id "
            f"WHERE {where} ORDER BY n.created_at DESC,n.id DESC "
            "LIMIT :limit OFFSET :offset"
        )
        count_statement = text(
            "SELECT count(*) AS total,"
            "count(*) FILTER (WHERE r.read_at IS NULL) AS unread_count "
            f"FROM {self._notifications} n JOIN {self._receipts} r "
            "ON r.notification_id=n.id AND r.user_id=:recipient_user_id "
            f"WHERE {where}"
        )
        if source_types:
            statement = statement.bindparams(bindparam("source_types", expanding=True))
            count_statement = count_statement.bindparams(
                bindparam("source_types", expanding=True)
            )
        async with self._session_factory() as session:
            rows = (await session.execute(statement, params)).mappings().all()
            counts = (await session.execute(count_statement, params)).mappings().one()
        return (
            [_event_from_row(row) for row in rows],
            int(counts["total"]),
            int(counts["unread_count"]),
        )

    async def mark_read(
        self,
        event_ids: list[str],
        *,
        recipient_user_id: UUID,
    ) -> int:
        parsed = [_optional_uuid(item) for item in event_ids]
        ids = [item for item in parsed if item is not None]
        if not ids:
            return 0
        statement = text(
            f"UPDATE {self._receipts} SET read_at=now() "
            "WHERE user_id=:user_id AND notification_id IN :ids "
            "AND read_at IS NULL AND deleted_at IS NULL"
        ).bindparams(bindparam("ids", expanding=True))
        async with self._session_factory() as session:
            result = await session.execute(
                statement,
                {"user_id": recipient_user_id, "ids": ids},
            )
        return int(result.rowcount or 0)

    async def mark_all_read(self, *, recipient_user_id: UUID) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"UPDATE {self._receipts} SET read_at=now() "
                    "WHERE user_id=:user_id AND read_at IS NULL "
                    "AND deleted_at IS NULL"
                ),
                {"user_id": recipient_user_id},
            )
        return int(result.rowcount or 0)

    async def delete_events(
        self,
        event_ids: list[str],
        *,
        recipient_user_id: UUID,
    ) -> int:
        parsed = [_optional_uuid(item) for item in event_ids]
        ids = [item for item in parsed if item is not None]
        if not ids:
            return 0
        statement = text(
            f"UPDATE {self._receipts} SET deleted_at=now() "
            "WHERE user_id=:user_id AND notification_id IN :ids "
            "AND deleted_at IS NULL"
        ).bindparams(bindparam("ids", expanding=True))
        async with self._session_factory() as session:
            result = await session.execute(
                statement,
                {"user_id": recipient_user_id, "ids": ids},
            )
        return int(result.rowcount or 0)

    async def has_run_reference(
        self,
        run_id: str,
        *,
        recipient_user_id: UUID,
    ) -> bool:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT n.payload_ref "
                            f"FROM {self._notifications} n JOIN {self._receipts} r "
                            "ON r.notification_id=n.id AND r.user_id=:user_id "
                            "WHERE n.recipient_user_id=:user_id AND r.deleted_at IS NULL"
                        ),
                        {"user_id": recipient_user_id},
                    )
                )
                .scalars()
                .all()
            )
        return any(_decode_payload_ref(raw)[2].get("run_id") == run_id for raw in rows)
