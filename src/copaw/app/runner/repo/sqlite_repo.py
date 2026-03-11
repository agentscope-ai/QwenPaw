# -*- coding: utf-8 -*-
"""SQLite-based chat repository."""
from __future__ import annotations

from pathlib import Path

from .base import BaseChatRepository
from ..models import ChatSpec, ChatsFile
from ...channels.schema import DEFAULT_CHANNEL
from ...state_db import (
    connect_state_db,
    dump_model_payload,
    ensure_state_db_schema,
    load_chat_from_row,
)


class SQLiteChatRepository(BaseChatRepository):
    """SQLite-backed repository for chat specifications."""

    def __init__(self, db_path: Path | str):
        if isinstance(db_path, str):
            db_path = Path(db_path)
        self._db_path = db_path.expanduser()
        ensure_state_db_schema(self._db_path)

    @property
    def path(self) -> Path:
        return self._db_path

    async def load(self) -> ChatsFile:
        with connect_state_db(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM chats
                ORDER BY created_at ASC, id ASC
                """,
            ).fetchall()
        return ChatsFile(
            version=1,
            chats=[load_chat_from_row(row) for row in rows],
        )

    async def save(self, chats_file: ChatsFile) -> None:
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM chats")
                conn.executemany(
                    """
                    INSERT INTO chats (
                        id,
                        session_id,
                        user_id,
                        channel,
                        created_at,
                        updated_at,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            chat.id,
                            chat.session_id,
                            chat.user_id,
                            chat.channel,
                            chat.created_at.isoformat(),
                            chat.updated_at.isoformat(),
                            dump_model_payload(chat),
                        )
                        for chat in chats_file.chats
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    async def get_chat(self, chat_id: str) -> ChatSpec | None:
        with connect_state_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM chats WHERE id = ?",
                (chat_id,),
            ).fetchone()
        return load_chat_from_row(row) if row is not None else None

    async def get_chat_by_id(
        self,
        session_id: str,
        user_id: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> ChatSpec | None:
        with connect_state_db(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM chats
                WHERE session_id = ? AND user_id = ? AND channel = ?
                """,
                (session_id, user_id, channel),
            ).fetchone()
        return load_chat_from_row(row) if row is not None else None

    async def upsert_chat(self, spec: ChatSpec) -> None:
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM chats
                    WHERE id = ?
                       OR (session_id = ? AND user_id = ? AND channel = ?)
                    ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (
                        spec.id,
                        spec.session_id,
                        spec.user_id,
                        spec.channel,
                        spec.id,
                    ),
                ).fetchone()

                if row is not None:
                    existing = load_chat_from_row(row)
                    if spec.id != existing.id:
                        spec.id = existing.id
                        spec.created_at = existing.created_at
                    conn.execute(
                        """
                        UPDATE chats
                        SET session_id = ?,
                            user_id = ?,
                            channel = ?,
                            created_at = ?,
                            updated_at = ?,
                            payload_json = ?
                        WHERE id = ?
                        """,
                        (
                            spec.session_id,
                            spec.user_id,
                            spec.channel,
                            spec.created_at.isoformat(),
                            spec.updated_at.isoformat(),
                            dump_model_payload(spec),
                            spec.id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO chats (
                            id,
                            session_id,
                            user_id,
                            channel,
                            created_at,
                            updated_at,
                            payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            spec.id,
                            spec.session_id,
                            spec.user_id,
                            spec.channel,
                            spec.created_at.isoformat(),
                            spec.updated_at.isoformat(),
                            dump_model_payload(spec),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        if not chat_ids:
            return False

        placeholders = ", ".join("?" for _ in chat_ids)
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = conn.execute(
                    f"DELETE FROM chats WHERE id IN ({placeholders})",
                    tuple(chat_ids),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result.rowcount > 0

    async def filter_chats(
        self,
        user_id: str | None = None,
        channel: str | None = None,
    ) -> list[ChatSpec]:
        clauses: list[str] = []
        params: list[str] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if channel is not None:
            clauses.append("channel = ?")
            params.append(channel)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect_state_db(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT payload_json
                FROM chats
                {where}
                ORDER BY created_at ASC, id ASC
                """,
                tuple(params),
            ).fetchall()
        return [load_chat_from_row(row) for row in rows]
