# -*- coding: utf-8 -*-
"""Durable, display-faithful chat transcript storage."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ...runtime.console_turn_state import TURN_STATE
from ...schemas import Message, RunStatus
from ...token_usage.turn_usage import TURN_USAGE_META_KEY

_SCHEMA_VERSION = 3
_BUSY_TIMEOUT_MS = 5000
_DELETE_BATCH_SIZE = 5_000
logger = logging.getLogger(__name__)
TurnStatus = Literal["running", "completed", "failed", "cancelled"]
Completeness = Literal["complete", "partial"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


@dataclass(frozen=True)
class TranscriptPage:
    """One turn-bounded transcript page in chronological display order."""

    messages: list[Message]
    next_before: int | None
    has_more: bool
    revision: int
    completeness: Completeness


class TranscriptStore:
    """Workspace-owned SQLite store for user-visible chat transcripts."""

    def __init__(
        self,
        db_path: str | Path,
        retention_days: int = 30,
    ) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._retention_days = retention_days
        self._last_retention_check: date | None = None
        self._cleanup_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="transcript-cleanup",
        )
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        self._conn.execute("PRAGMA journal_mode=WAL")
        try:
            self._migrate()
            self.purge_if_due()
            self._submit_cleanup(self._purge_deleted_sessions)
        except BaseException:
            self._cleanup_executor.shutdown(wait=False, cancel_futures=True)
            self._conn.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        """Return the transcript database path."""
        return self._path

    @property
    def closed(self) -> bool:
        """Return whether the store was intentionally closed."""
        return self._closed

    def _migrate(self) -> None:
        with self._lock, self._conn:
            version = int(
                self._conn.execute("PRAGMA user_version").fetchone()[0],
            )
            if version > _SCHEMA_VERSION:
                raise RuntimeError(
                    f"transcript schema {version} is newer than supported "
                    f"version {_SCHEMA_VERSION}",
                )
            if version == 0:
                self._create_schema_v3()
                self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                return
            if version == 1:
                self._conn.execute(
                    "ALTER TABLE transcript_turns "
                    "ADD COLUMN replaces_turn_id TEXT",
                )
                version = 2
            if version == 2:
                self._migrate_v3_client_message_ids()
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def _create_schema_v3(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE transcript_sessions (
                session_id       TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL,
                channel          TEXT NOT NULL,
                revision         INTEGER NOT NULL DEFAULT 0,
                next_turn_seq    INTEGER NOT NULL DEFAULT 1,
                completeness     TEXT NOT NULL DEFAULT 'complete'
                                 CHECK(completeness IN (
                                     'complete', 'partial'
                                 )),
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                deleted_at       TEXT
            );

            CREATE TABLE transcript_turns (
                session_id       TEXT NOT NULL,
                turn_seq         INTEGER NOT NULL,
                turn_id          TEXT NOT NULL,
                status           TEXT NOT NULL
                                 CHECK(status IN (
                                     'running', 'completed',
                                     'failed', 'cancelled'
                                 )),
                error_json       TEXT,
                source           TEXT NOT NULL,
                source_complete  INTEGER NOT NULL DEFAULT 1,
                replaces_turn_id TEXT,
                created_at       TEXT NOT NULL,
                finished_at      TEXT,
                PRIMARY KEY(session_id, turn_seq),
                UNIQUE(session_id, turn_id),
                FOREIGN KEY(session_id)
                    REFERENCES transcript_sessions(session_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX transcript_turns_page
                ON transcript_turns(session_id, turn_seq DESC);

            CREATE TABLE transcript_messages (
                session_id          TEXT NOT NULL,
                turn_id             TEXT NOT NULL,
                message_id          TEXT NOT NULL,
                ordinal             INTEGER NOT NULL,
                role                TEXT NOT NULL,
                kind                TEXT NOT NULL,
                payload_json        TEXT NOT NULL,
                status              TEXT NOT NULL,
                client_message_id   TEXT,
                replaces_message_id TEXT,
                superseded_at       TEXT,
                created_at          TEXT NOT NULL,
                finished_at         TEXT,
                PRIMARY KEY(session_id, message_id),
                UNIQUE(session_id, turn_id, ordinal),
                FOREIGN KEY(session_id, turn_id)
                    REFERENCES transcript_turns(session_id, turn_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX transcript_messages_turn
                ON transcript_messages(session_id, turn_id, ordinal);

            CREATE INDEX transcript_messages_client
                ON transcript_messages(
                    session_id, client_message_id, created_at DESC
                );

            CREATE TABLE transcript_imports (
                source_kind      TEXT NOT NULL,
                source_identity  TEXT NOT NULL,
                fingerprint      TEXT NOT NULL,
                schema_version   INTEGER NOT NULL,
                imported_at      TEXT NOT NULL,
                result_json      TEXT NOT NULL,
                PRIMARY KEY(
                    source_kind,
                    source_identity,
                    fingerprint,
                    schema_version
                )
            );
            """,
        )

    def _migrate_v3_client_message_ids(self) -> None:
        """Add and backfill the indexed client message identifier."""
        started = time.perf_counter()
        self._conn.execute(
            "ALTER TABLE transcript_messages "
            "ADD COLUMN client_message_id TEXT",
        )
        cursor = self._conn.execute(
            "UPDATE transcript_messages SET client_message_id = "
            "json_extract(payload_json, ?) WHERE role = 'user'",
            (f"$.metadata.{QWENPAW_CLIENT_MESSAGE_ID_KEY}",),
        )
        self._conn.execute(
            "CREATE INDEX transcript_messages_client "
            "ON transcript_messages("
            "session_id, client_message_id, created_at DESC)",
        )
        logger.info(
            "Transcript v3 client-id migration rows=%s elapsed_ms=%.1f",
            max(cursor.rowcount, 0),
            (time.perf_counter() - started) * 1000,
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

    def _session_row(self, session_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
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
        source: str,
        source_complete: bool = True,
        replaces_turn_id: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """Create a running turn and return its stable sequence."""
        timestamp = created_at or _utc_now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, user_id, channel, completeness, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (
                    session_id,
                    user_id,
                    channel,
                    "complete" if source_complete else "partial",
                    timestamp,
                    timestamp,
                ),
            )
            session = self._session_row(session_id)
            assert session is not None
            if session["deleted_at"] is not None:
                raise ValueError("transcript session is deleted")
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
                return int(existing["turn_seq"])

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
                "session_id, turn_seq, turn_id, status, source, "
                "source_complete, replaces_turn_id, created_at) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?, ?)",
                (
                    session_id,
                    turn_seq,
                    turn_id,
                    source,
                    int(source_complete),
                    replaces_turn_id,
                    timestamp,
                ),
            )
            completeness = (
                "partial"
                if not source_complete or session["completeness"] == "partial"
                else "complete"
            )
            self._conn.execute(
                "UPDATE transcript_sessions SET "
                "next_turn_seq = ?, revision = revision + 1, "
                "completeness = ?, updated_at = ? "
                "WHERE session_id = ?",
                (
                    turn_seq + 1,
                    completeness,
                    timestamp,
                    session_id,
                ),
            )
            return turn_seq

    def import_history_if_missing(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        source: str,
        turns: list[tuple[str, list[Message]]],
        source_complete: bool = False,
        imported_at: str | None = None,
    ) -> bool:
        """Atomically import history without replacing a live session."""
        normalized = [
            (turn_id, messages) for turn_id, messages in turns if messages
        ]
        if not normalized:
            return False
        timestamp = imported_at or _utc_now()
        revision = sum(len(messages) + 2 for _, messages in normalized)
        with self._transaction():
            if self._session_row(session_id) is not None:
                return False
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, user_id, channel, revision, next_turn_seq, "
                "completeness, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    channel,
                    revision,
                    len(normalized) + 1,
                    "complete" if source_complete else "partial",
                    timestamp,
                    timestamp,
                ),
            )
            for turn_seq, (turn_id, messages) in enumerate(
                normalized,
                start=1,
            ):
                self._conn.execute(
                    "INSERT INTO transcript_turns("
                    "session_id, turn_seq, turn_id, status, source, "
                    "source_complete, created_at, finished_at) "
                    "VALUES (?, ?, ?, 'completed', ?, ?, ?, ?)",
                    (
                        session_id,
                        turn_seq,
                        turn_id,
                        source,
                        int(source_complete),
                        timestamp,
                        timestamp,
                    ),
                )
                for ordinal, message in enumerate(messages):
                    self._conn.execute(
                        "INSERT INTO transcript_messages("
                        "session_id, turn_id, message_id, ordinal, role, "
                        "kind, payload_json, status, created_at, "
                        "client_message_id, finished_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            turn_id,
                            message.id,
                            ordinal,
                            _enum_value(message.role),
                            _enum_value(message.type),
                            message.model_dump_json(),
                            _enum_value(message.status),
                            timestamp,
                            self._client_message_id(message),
                            timestamp,
                        ),
                    )
            return True

    def upsert_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: Message,
        ordinal: int,
        replaces_message_id: str | None = None,
        created_at: str | None = None,
        finished_at: str | None = None,
    ) -> int:
        """Insert or update one complete display message snapshot."""
        payload = message.model_dump_json()
        role = _enum_value(message.role)
        kind = _enum_value(message.type)
        status = _enum_value(message.status)
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
                "SELECT turn_id, ordinal, role, kind, payload_json, status, "
                "client_message_id, replaces_message_id, finished_at "
                "FROM transcript_messages "
                "WHERE session_id = ? AND message_id = ?",
                (session_id, message.id),
            ).fetchone()
            values = (
                turn_id,
                ordinal,
                role,
                kind,
                payload,
                status,
                client_message_id,
                replaces_message_id,
                finished_at,
            )
            if existing is not None and tuple(existing) == values:
                return self._revision(session_id)
            if existing is not None and existing["turn_id"] != turn_id:
                raise ValueError("transcript message belongs to another turn")

            self._conn.execute(
                "INSERT INTO transcript_messages("
                "session_id, turn_id, message_id, ordinal, role, kind, "
                "payload_json, status, replaces_message_id, created_at, "
                "client_message_id, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, message_id) DO UPDATE SET "
                "turn_id = excluded.turn_id, ordinal = excluded.ordinal, "
                "role = excluded.role, kind = excluded.kind, "
                "payload_json = excluded.payload_json, "
                "status = excluded.status, "
                "client_message_id = excluded.client_message_id, "
                "replaces_message_id = excluded.replaces_message_id, "
                "finished_at = excluded.finished_at",
                (
                    session_id,
                    turn_id,
                    message.id,
                    ordinal,
                    role,
                    kind,
                    payload,
                    status,
                    replaces_message_id,
                    timestamp,
                    client_message_id,
                    finished_at,
                ),
            )
            return self._bump_revision(session_id, timestamp)

    def finish_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        status: TurnStatus,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> int:
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
                return self._revision(session_id)
            timestamp = finished_at or _utc_now()
            values = (status, error_json, timestamp)
            if tuple(existing)[:3] == values:
                return self._revision(session_id)
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
                self._conn.execute(
                    "UPDATE transcript_messages SET superseded_at = ? "
                    "WHERE session_id = ? AND message_id IN ("
                    "SELECT replaces_message_id FROM transcript_messages "
                    "WHERE session_id = ? AND turn_id = ? "
                    "AND replaces_message_id IS NOT NULL)",
                    (timestamp, session_id, session_id, turn_id),
                )
            return self._bump_revision(session_id, timestamp)

    def attach_turn_usage(
        self,
        *,
        session_id: str,
        turn_id: str,
        usage: dict[str, Any] | None,
        context_usage: dict[str, Any] | None,
    ) -> int | None:
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
                return None

            message = Message.model_validate_json(row["payload_json"])
            metadata = dict(message.metadata or {})
            if metadata.get(TURN_USAGE_META_KEY) == snapshot:
                return self._revision(session_id)

            metadata[TURN_USAGE_META_KEY] = snapshot
            updated = message.model_copy(
                update={"metadata": metadata},
                deep=True,
            )
            timestamp = _utc_now()
            self._conn.execute(
                "UPDATE transcript_messages SET payload_json = ? "
                "WHERE session_id = ? AND message_id = ?",
                (
                    updated.model_dump_json(),
                    session_id,
                    row["message_id"],
                ),
            )
            return self._bump_revision(session_id, timestamp)

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: int | None = None,
        limit: int = 50,
    ) -> TranscriptPage | None:
        """Read one turn-bounded page without replaying active outputs."""
        if limit < 1 or limit > 100:
            raise ValueError("transcript page limit must be between 1 and 100")
        with self._lock:
            session = self._session_row(session_id)
            if session is None or session["deleted_at"] is not None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            sql = (
                "SELECT turn_seq, turn_id FROM transcript_turns "
                "WHERE session_id = ? AND EXISTS ("
                "SELECT 1 FROM transcript_messages m "
                "WHERE m.session_id = transcript_turns.session_id "
                "AND m.turn_id = transcript_turns.turn_id "
                "AND m.superseded_at IS NULL "
                "AND (transcript_turns.status != 'running' "
                "OR m.role = 'user'))"
            )
            params: list[Any] = [session_id]
            if before is not None:
                sql += " AND turn_seq < ?"
                params.append(before)
            sql += " ORDER BY turn_seq DESC LIMIT ?"
            params.append(limit + 1)
            turns = self._conn.execute(sql, params).fetchall()
            has_more = len(turns) > limit
            selected = turns[:limit]
            if not selected:
                return TranscriptPage(
                    messages=[],
                    next_before=None,
                    has_more=False,
                    revision=int(session["revision"]),
                    completeness=session["completeness"],
                )
            turn_ids = [str(row["turn_id"]) for row in selected]
            placeholders = ", ".join("?" for _ in turn_ids)
            rows = self._conn.execute(
                "SELECT m.payload_json, "
                "m.created_at AS message_created_at, "
                "m.finished_at AS message_finished_at, "
                "t.status AS turn_status, t.error_json, "
                "t.finished_at AS turn_finished_at "
                "FROM transcript_messages m "
                "JOIN transcript_turns t "
                "ON t.session_id = m.session_id AND t.turn_id = m.turn_id "
                f"WHERE m.session_id = ? AND m.turn_id IN ({placeholders}) "
                "AND m.superseded_at IS NULL "
                "AND (t.status != 'running' OR m.role = 'user') "
                "ORDER BY t.turn_seq, m.ordinal",
                [session_id, *turn_ids],
            ).fetchall()
            next_before = (
                min(int(row["turn_seq"]) for row in selected)
                if has_more
                else None
            )
            return TranscriptPage(
                messages=[self._message_from_row(row) for row in rows],
                next_before=next_before,
                has_more=has_more,
                revision=int(session["revision"]),
                completeness=session["completeness"],
            )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> Message:
        """Project normalized transcript columns into the wire contract."""
        message = Message.model_validate_json(row["payload_json"])
        metadata = dict(message.metadata or {})
        metadata.setdefault("timestamp", row["message_created_at"])

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
        with self._lock:
            if message_id:
                row = self._conn.execute(
                    "SELECT turn_id FROM transcript_messages "
                    "WHERE session_id = ? AND message_id = ?",
                    (session_id, message_id),
                ).fetchone()
                if row is not None:
                    return str(row["turn_id"])
            if client_message_id:
                row = self._conn.execute(
                    "SELECT turn_id FROM transcript_messages "
                    "WHERE session_id = ? AND client_message_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id, client_message_id),
                ).fetchone()
                if row is not None:
                    return str(row["turn_id"])
        return None

    def _revision(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT revision FROM transcript_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ValueError("transcript session does not exist")
        return int(row["revision"])

    def _bump_revision(self, session_id: str, timestamp: str) -> int:
        self._conn.execute(
            "UPDATE transcript_sessions SET revision = revision + 1, "
            "updated_at = ? WHERE session_id = ?",
            (timestamp, session_id),
        )
        return self._revision(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Hide and securely remove one transcript."""
        if not self.mark_session_deleted(session_id):
            return False
        return self._purge_deleted_session(session_id)

    def mark_session_deleted(self, session_id: str) -> bool:
        """Hide a transcript durably before asynchronous physical cleanup."""
        with self._transaction():
            existing = self._conn.execute(
                "SELECT 1 FROM transcript_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is None:
                return False
            self._conn.execute(
                "UPDATE transcript_sessions SET deleted_at = ?, "
                "revision = revision + 1, updated_at = ? "
                "WHERE session_id = ?",
                (_utc_now(), _utc_now(), session_id),
            )
            return True

    def schedule_delete_session(self, session_id: str) -> bool:
        """Hide a transcript now and securely purge it in the background."""
        if not self.mark_session_deleted(session_id):
            return False
        self._submit_cleanup(self._purge_deleted_session, session_id)
        return True

    def _purge_deleted_session(self, session_id: str) -> bool:
        started = time.perf_counter()
        with self._lock:
            marked = self._conn.execute(
                "SELECT 1 FROM transcript_sessions "
                "WHERE session_id = ? AND deleted_at IS NOT NULL",
                (session_id,),
            ).fetchone()
        if marked is None:
            return False
        deleted_messages = self._delete_session_rows(
            "transcript_messages",
            session_id,
        )
        deleted_turns = self._delete_session_rows(
            "transcript_turns",
            session_id,
        )
        with self._transaction():
            existing = self._conn.execute(
                "SELECT 1 FROM transcript_sessions "
                "WHERE session_id = ? AND deleted_at IS NOT NULL",
                (session_id,),
            ).fetchone()
            if existing is None:
                return False
            cursor = self._conn.execute(
                "DELETE FROM transcript_sessions WHERE session_id = ?",
                (session_id,),
            )
            deleted = bool(cursor.rowcount)
        logger.info(
            "Transcript cleanup messages=%s turns=%s elapsed_ms=%.1f",
            deleted_messages,
            deleted_turns,
            (time.perf_counter() - started) * 1000,
        )
        return deleted

    def _delete_session_rows(self, table: str, session_id: str) -> int:
        if table not in {"transcript_messages", "transcript_turns"}:
            raise ValueError("invalid transcript cleanup table")
        removed = 0
        while True:
            with self._transaction():
                cursor = self._conn.execute(
                    f"DELETE FROM {table} WHERE rowid IN ("
                    f"SELECT rowid FROM {table} WHERE session_id = ? "
                    "LIMIT ?)",
                    (session_id, _DELETE_BATCH_SIZE),
                )
                batch = max(cursor.rowcount, 0)
            removed += batch
            if batch < _DELETE_BATCH_SIZE:
                return removed
            time.sleep(0)

    def _purge_deleted_sessions(self) -> None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id FROM transcript_sessions "
                "WHERE deleted_at IS NOT NULL",
            ).fetchall()
        for row in rows:
            self._purge_deleted_session(str(row["session_id"]))

    def _submit_cleanup(
        self,
        method: Any,
        *args: Any,
    ) -> Future[Any] | None:
        with self._lock:
            if self._closed:
                return None
            future = self._cleanup_executor.submit(method, *args)

        def _log_failure(completed: Future[Any]) -> None:
            try:
                completed.result()
            except Exception:
                logger.warning(
                    "Transcript background cleanup failed",
                    exc_info=True,
                )

        future.add_done_callback(_log_failure)
        return future

    def has_session(self, session_id: str) -> bool:
        """Return whether the transcript owns the session identifier."""
        with self._lock:
            row = self._session_row(session_id)
            return row is not None and row["deleted_at"] is None

    def has_import(
        self,
        *,
        source_kind: str,
        source_identity: str,
        fingerprint: str,
        schema_version: int,
    ) -> bool:
        """Return whether one exact migration source was processed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM transcript_imports WHERE source_kind = ? "
                "AND source_identity = ? AND fingerprint = ? "
                "AND schema_version = ?",
                (
                    source_kind,
                    source_identity,
                    fingerprint,
                    schema_version,
                ),
            ).fetchone()
            return row is not None

    def purge_old(
        self,
        retention_days: int,
        *,
        now: datetime | None = None,
    ) -> int:
        """Delete terminal turns outside retention and preserve a marker."""
        if retention_days <= 0:
            return 0
        current = now or datetime.now(timezone.utc)
        cutoff = (current - timedelta(days=retention_days)).isoformat()
        timestamp = current.isoformat()
        with self._transaction():
            sessions = self._conn.execute(
                "SELECT DISTINCT session_id FROM transcript_turns "
                "WHERE created_at < ? AND status != 'running'",
                (cutoff,),
            ).fetchall()
            cursor = self._conn.execute(
                "DELETE FROM transcript_turns "
                "WHERE created_at < ? AND status != 'running'",
                (cutoff,),
            )
            for row in sessions:
                self._conn.execute(
                    "UPDATE transcript_sessions SET completeness = 'partial', "
                    "revision = revision + 1, updated_at = ? "
                    "WHERE session_id = ?",
                    (timestamp, row["session_id"]),
                )
            return int(cursor.rowcount)

    def purge_if_due(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        """Apply retention at most once per UTC day for a live workspace."""
        if self._retention_days <= 0:
            return 0
        current = now or datetime.now(timezone.utc)
        with self._lock:
            if self._last_retention_check == current.date():
                return 0
            removed = self.purge_old(
                self._retention_days,
                now=current,
            )
            self._last_retention_check = current.date()
            return removed

    def record_import(
        self,
        *,
        source_kind: str,
        source_identity: str,
        fingerprint: str,
        schema_version: int,
        result: dict[str, Any],
    ) -> bool:
        """Record one completed migration source idempotently."""
        with self._transaction():
            cursor = self._conn.execute(
                "INSERT INTO transcript_imports("
                "source_kind, source_identity, fingerprint, schema_version, "
                "imported_at, result_json) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                (
                    source_kind,
                    source_identity,
                    fingerprint,
                    schema_version,
                    _utc_now(),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                ),
            )
            return bool(cursor.rowcount)

    def close(self) -> None:
        """Close the SQLite connection idempotently."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._cleanup_executor.shutdown(wait=True)
        with self._lock:
            self._conn.close()


__all__ = ["TranscriptPage", "TranscriptStore"]
