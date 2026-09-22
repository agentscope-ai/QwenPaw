# -*- coding: utf-8 -*-
"""Durable, display-faithful chat transcript storage."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ...runtime.console_turn_state import TURN_STATE
from ...schemas import Message, RunStatus
from ...token_usage.turn_usage import TURN_USAGE_META_KEY

_BUSY_TIMEOUT_MS = 5000
TurnStatus = Literal["running", "completed", "failed", "cancelled"]
_DEFAULT_PAGE_MAX_BYTES = 512 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


@dataclass(frozen=True)
class TranscriptCursor:
    """Exclusive position before which an older page is read."""

    turn_seq: int
    ordinal: int


@dataclass(frozen=True)
class TranscriptPage:
    """One item-bounded transcript page in chronological display order."""

    messages: list[Message]
    next_before: TranscriptCursor | None
    has_more: bool


class TranscriptStore:
    """Workspace-owned SQLite store for user-visible chat transcripts."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        try:
            self._conn.execute("PRAGMA journal_mode=DELETE")
            with self._conn:
                self._create_schema()
        except BaseException:
            self._conn.close()
            self._closed = True
            raise

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived read-only connection for page reads."""
        uri = f"{self._path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transcript_sessions (
                session_id       TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL,
                channel          TEXT NOT NULL,
                next_turn_seq    INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS transcript_turns (
                session_id       TEXT NOT NULL,
                turn_seq         INTEGER NOT NULL,
                turn_id          TEXT NOT NULL,
                status           TEXT NOT NULL
                                 CHECK(status IN (
                                     'running', 'completed',
                                     'failed', 'cancelled'
                )),
                error_json       TEXT,
                replaces_turn_id TEXT,
                created_at       TEXT NOT NULL,
                finished_at      TEXT,
                PRIMARY KEY(session_id, turn_seq),
                UNIQUE(session_id, turn_id),
                FOREIGN KEY(session_id)
                    REFERENCES transcript_sessions(session_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS transcript_messages (
                session_id          TEXT NOT NULL,
                turn_id             TEXT NOT NULL,
                message_id          TEXT NOT NULL,
                ordinal             INTEGER NOT NULL,
                role                TEXT NOT NULL,
                payload_json        TEXT NOT NULL,
                client_message_id   TEXT,
                superseded_at       TEXT,
                created_at          TEXT NOT NULL,
                finished_at         TEXT,
                PRIMARY KEY(session_id, message_id),
                UNIQUE(session_id, turn_id, ordinal),
                FOREIGN KEY(session_id, turn_id)
                    REFERENCES transcript_turns(session_id, turn_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS transcript_messages_client
                ON transcript_messages(
                    session_id, client_message_id, created_at DESC
                );

            """,
        )

    @staticmethod
    def _client_message_id(message: Message) -> str | None:
        metadata = message.metadata or {}
        value = metadata.get(QWENPAW_CLIENT_MESSAGE_ID_KEY)
        return str(value) if value else None

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.rollback()
                raise
            self._conn.commit()

    def _session_row(
        self,
        session_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        database = connection or self._conn
        return database.execute(
            "SELECT * FROM transcript_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    @staticmethod
    def _assert_identity(
        row: sqlite3.Row,
        *,
        user_id: str,
        channel: str,
    ) -> None:
        if row["user_id"] != user_id or row["channel"] != channel:
            raise ValueError("transcript session identity mismatch")

    def start_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        turn_id: str,
        replaces_turn_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Create a running turn if it does not already exist."""
        timestamp = created_at or _utc_now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, user_id, channel) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (
                    session_id,
                    user_id,
                    channel,
                ),
            )
            session = self._session_row(session_id)
            assert session is not None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            existing = self._conn.execute(
                "SELECT turn_seq, replaces_turn_id FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if existing is not None:
                if existing["replaces_turn_id"] != replaces_turn_id:
                    raise ValueError("transcript replacement target mismatch")
                return

            if replaces_turn_id is not None:
                replacement = self._conn.execute(
                    "SELECT 1 FROM transcript_turns "
                    "WHERE session_id = ? AND turn_id = ?",
                    (session_id, replaces_turn_id),
                ).fetchone()
                if replacement is None:
                    raise ValueError("replacement transcript turn not found")

            turn_seq = int(session["next_turn_seq"])
            self._conn.execute(
                "INSERT INTO transcript_turns("
                "session_id, turn_seq, turn_id, status, "
                "replaces_turn_id, created_at) "
                "VALUES (?, ?, ?, 'running', ?, ?)",
                (
                    session_id,
                    turn_seq,
                    turn_id,
                    replaces_turn_id,
                    timestamp,
                ),
            )
            self._conn.execute(
                "UPDATE transcript_sessions SET "
                "next_turn_seq = ? WHERE session_id = ?",
                (
                    turn_seq + 1,
                    session_id,
                ),
            )

    def upsert_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: Message,
        ordinal: int,
        created_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        """Insert or update one complete display message snapshot."""
        payload = message.model_dump_json()
        role = _enum_value(message.role)
        client_message_id = self._client_message_id(message)
        timestamp = created_at or _utc_now()
        with self._transaction():
            turn = self._conn.execute(
                "SELECT 1 FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if turn is None:
                raise ValueError("transcript turn does not exist")
            existing = self._conn.execute(
                "SELECT turn_id, ordinal, role, payload_json, "
                "client_message_id, finished_at "
                "FROM transcript_messages "
                "WHERE session_id = ? AND message_id = ?",
                (session_id, message.id),
            ).fetchone()
            values = (
                turn_id,
                ordinal,
                role,
                payload,
                client_message_id,
                finished_at,
            )
            if existing is not None and tuple(existing) == values:
                return
            if existing is not None and existing["turn_id"] != turn_id:
                raise ValueError("transcript message belongs to another turn")

            self._conn.execute(
                "INSERT INTO transcript_messages("
                "session_id, turn_id, message_id, ordinal, role, "
                "payload_json, created_at, "
                "client_message_id, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, message_id) DO UPDATE SET "
                "turn_id = excluded.turn_id, ordinal = excluded.ordinal, "
                "role = excluded.role, "
                "payload_json = excluded.payload_json, "
                "client_message_id = excluded.client_message_id, "
                "finished_at = excluded.finished_at",
                (
                    session_id,
                    turn_id,
                    message.id,
                    ordinal,
                    role,
                    payload,
                    timestamp,
                    client_message_id,
                    finished_at,
                ),
            )

    def finish_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        status: TurnStatus,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> None:
        """Set a terminal turn status and activate successful replacements."""
        if status == "running":
            raise ValueError("finish_turn requires a terminal status")
        error_json = (
            json.dumps(error, ensure_ascii=False, sort_keys=True)
            if error is not None
            else None
        )
        with self._transaction():
            existing = self._conn.execute(
                "SELECT status, error_json, finished_at, replaces_turn_id "
                "FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if existing is None:
                raise ValueError("transcript turn does not exist")
            if (
                finished_at is None
                and existing["status"] == status
                and existing["error_json"] == error_json
                and existing["finished_at"] is not None
            ):
                return
            timestamp = finished_at or _utc_now()
            values = (status, error_json, timestamp)
            if tuple(existing)[:3] == values:
                return
            self._conn.execute(
                "UPDATE transcript_turns SET status = ?, error_json = ?, "
                "finished_at = ? WHERE session_id = ? AND turn_id = ?",
                (status, error_json, timestamp, session_id, turn_id),
            )
            if status == "completed":
                if existing["replaces_turn_id"] is not None:
                    self._conn.execute(
                        "UPDATE transcript_messages SET superseded_at = ? "
                        "WHERE session_id = ? AND turn_id = ? "
                        "AND superseded_at IS NULL",
                        (
                            timestamp,
                            session_id,
                            existing["replaces_turn_id"],
                        ),
                    )

    def attach_turn_usage(
        self,
        *,
        session_id: str,
        turn_id: str,
        usage: dict[str, Any] | None,
        context_usage: dict[str, Any] | None,
    ) -> bool:
        """Attach one usage snapshot to the turn's closing assistant."""
        snapshot = {
            "usage": usage,
            "context_usage": context_usage,
        }
        with self._transaction():
            row = self._conn.execute(
                "SELECT message_id, payload_json "
                "FROM transcript_messages "
                "WHERE session_id = ? AND turn_id = ? "
                "AND role = 'assistant' "
                "ORDER BY ordinal DESC LIMIT 1",
                (session_id, turn_id),
            ).fetchone()
            if row is None:
                return False

            message = Message.model_validate_json(row["payload_json"])
            metadata = dict(message.metadata or {})
            if metadata.get(TURN_USAGE_META_KEY) == snapshot:
                return True

            metadata[TURN_USAGE_META_KEY] = snapshot
            updated = message.model_copy(
                update={"metadata": metadata},
                deep=True,
            )
            self._conn.execute(
                "UPDATE transcript_messages SET payload_json = ? "
                "WHERE session_id = ? AND message_id = ?",
                (
                    updated.model_dump_json(),
                    session_id,
                    row["message_id"],
                ),
            )
            return True

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
        limit: int = 50,
        max_bytes: int = _DEFAULT_PAGE_MAX_BYTES,
    ) -> TranscriptPage | None:
        """Read one item-bounded page without replaying active outputs."""
        if limit < 1 or limit > 100:
            raise ValueError("transcript page limit must be between 1 and 100")
        if max_bytes < 1:
            raise ValueError("transcript page max_bytes must be positive")
        with self._read_connection() as connection:
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            sql = (
                "SELECT m.payload_json, length(CAST(m.payload_json AS BLOB)) "
                "AS payload_bytes, m.created_at AS message_created_at, "
                "m.finished_at AS message_finished_at, m.ordinal, "
                "t.turn_id, t.turn_seq, t.status AS turn_status, "
                "t.error_json, t.finished_at AS turn_finished_at "
                "FROM transcript_messages m JOIN transcript_turns t "
                "ON t.session_id = m.session_id AND t.turn_id = m.turn_id "
                "WHERE m.session_id = ? AND m.superseded_at IS NULL "
                "AND (t.status != 'running' OR m.role = 'user')"
            )
            params: list[Any] = [session_id]
            if before is not None:
                sql += (
                    " AND (t.turn_seq < ? OR (t.turn_seq = ? "
                    "AND m.ordinal < ?))"
                )
                params.extend(
                    [before.turn_seq, before.turn_seq, before.ordinal],
                )
            sql += " ORDER BY t.turn_seq DESC, m.ordinal DESC LIMIT ?"
            params.append(limit + 1)
            candidates = connection.execute(sql, params).fetchall()
            selected: list[sqlite3.Row] = []
            payload_bytes = 0
            for row in candidates[:limit]:
                row_bytes = int(row["payload_bytes"])
                if selected and payload_bytes + row_bytes > max_bytes:
                    break
                selected.append(row)
                payload_bytes += row_bytes
                if payload_bytes >= max_bytes:
                    break
            has_more = len(selected) < len(candidates)
            if not selected:
                return TranscriptPage(
                    messages=[],
                    next_before=None,
                    has_more=False,
                )
            selected.reverse()
            first = selected[0]
            next_before = None
            if has_more:
                next_before = TranscriptCursor(
                    turn_seq=int(first["turn_seq"]),
                    ordinal=int(first["ordinal"]),
                )
            return TranscriptPage(
                messages=[self._message_from_row(row) for row in selected],
                next_before=next_before,
                has_more=has_more,
            )

    @staticmethod
    def _message_from_row(
        row: sqlite3.Row,
    ) -> Message:
        """Project normalized transcript columns into the wire contract."""
        message = Message.model_validate_json(row["payload_json"])
        metadata = dict(message.metadata or {})
        metadata.setdefault("timestamp", row["message_created_at"])
        metadata["qwenpaw_transcript_position"] = {
            "turn_id": str(row["turn_id"]),
            "turn_seq": int(row["turn_seq"]),
            "ordinal": int(row["ordinal"]),
        }

        turn_status = str(row["turn_status"])
        terminal = turn_status != "running"
        if terminal and _enum_value(message.role) != "user":
            finished_at = row["message_finished_at"] or row["turn_finished_at"]
            if finished_at is not None:
                metadata.setdefault("finished_at", finished_at)

        if terminal and _enum_value(message.role) == "user":
            state_metadata = metadata
            nested_metadata = metadata.get("metadata")
            if isinstance(nested_metadata, dict):
                state_metadata = dict(nested_metadata)
                metadata["metadata"] = state_metadata
            state = {"status": turn_status}
            if turn_status == "cancelled":
                state["status"] = "canceled"
            if turn_status == "failed" and row["error_json"]:
                state["error"] = json.loads(row["error_json"])
            state_metadata.setdefault(TURN_STATE, state)

        updates: dict[str, Any] = {"metadata": metadata}
        if terminal:
            updates["status"] = RunStatus.Completed
        return message.model_copy(update=updates)

    def find_turn_for_message(
        self,
        *,
        session_id: str,
        message_id: str | None = None,
        client_message_id: str | None = None,
    ) -> str | None:
        """Resolve a regeneration target to its transcript turn."""
        if not message_id and not client_message_id:
            return None
        with self._read_connection() as connection:
            if message_id:
                row = connection.execute(
                    "SELECT turn_id FROM transcript_messages "
                    "WHERE session_id = ? AND message_id = ?",
                    (session_id, message_id),
                ).fetchone()
                if row is not None:
                    return str(row["turn_id"])
            if client_message_id:
                row = connection.execute(
                    "SELECT turn_id FROM transcript_messages "
                    "WHERE session_id = ? AND client_message_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id, client_message_id),
                ).fetchone()
                if row is not None:
                    return str(row["turn_id"])
        return None

    def close(self) -> None:
        """Close the SQLite connection idempotently."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()


__all__ = ["TranscriptCursor", "TranscriptPage", "TranscriptStore"]
