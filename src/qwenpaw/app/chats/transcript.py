# -*- coding: utf-8 -*-
"""Durable, display-faithful chat transcript storage."""

from __future__ import annotations

import json
import sqlite3
import tempfile
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
_DEFAULT_PAGE_MAX_BYTES = 2 * 1024 * 1024


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
    """One byte-bounded transcript page in chronological display order."""

    messages: list[Message]
    next_before: TranscriptCursor | None
    has_more: bool


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Persisted agent runtime state for one conversation context."""

    state: dict[str, Any]
    context_generation: int
    current_usage: dict[str, Any] | None


class TranscriptStore:
    """Workspace-owned SQLite store for user-visible chat transcripts."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        initialize_schema: bool = True,
    ) -> None:
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
            needs_schema = initialize_schema or not self._schema_exists()
            if needs_schema:
                self._conn.execute("PRAGMA journal_mode=DELETE")
                with self._conn:
                    self._create_schema()
        except BaseException:
            self._conn.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        """Return the database path owned by this store."""
        return self._path

    def _schema_exists(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('transcript_sessions', 'session_runtime')",
        ).fetchone()
        return row is not None and int(row[0]) == 2

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

            CREATE TABLE IF NOT EXISTS session_runtime (
                session_id          TEXT PRIMARY KEY,
                context_generation  INTEGER NOT NULL DEFAULT 0,
                state_json          TEXT NOT NULL,
                current_usage_json  TEXT,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY(session_id)
                    REFERENCES transcript_sessions(session_id)
                    ON DELETE CASCADE
            );

            """,
        )

    @staticmethod
    def _client_message_id(message: Message) -> str | None:
        metadata = message.metadata or {}
        value = metadata.get(QWENPAW_CLIENT_MESSAGE_ID_KEY)
        nested = metadata.get("metadata")
        if not value and isinstance(nested, dict):
            value = nested.get(QWENPAW_CLIENT_MESSAGE_ID_KEY)
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

    def has_session(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bool:
        """Return whether this database already owns the session."""
        with self._read_connection() as connection:
            session = self._session_row(session_id, connection)
            if session is None:
                return False
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            return True

    def read_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> RuntimeSnapshot | None:
        """Read the current runtime snapshot without mutating the store."""
        with self._read_connection() as connection:
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            row = connection.execute(
                "SELECT state_json, context_generation, current_usage_json "
                "FROM session_runtime WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return RuntimeSnapshot(
                state=json.loads(row["state_json"]),
                context_generation=int(row["context_generation"]),
                current_usage=(
                    json.loads(row["current_usage_json"])
                    if row["current_usage_json"]
                    else None
                ),
            )

    def write_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        state: dict[str, Any],
        current_usage: dict[str, Any] | None = None,
        reset_context: bool = False,
        only_if_missing: bool = False,
    ) -> tuple[int, bool]:
        """Persist one runtime snapshot and optionally start a new context."""
        state_json = json.dumps(
            state,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        timestamp = _utc_now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, user_id, channel) "
                "VALUES (?, ?, ?) ON CONFLICT(session_id) DO NOTHING",
                (session_id, user_id, channel),
            )
            session = self._session_row(session_id)
            if session is None:
                raise RuntimeError("failed to create transcript session")
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            existing = self._conn.execute(
                "SELECT context_generation, current_usage_json "
                "FROM session_runtime WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is not None and only_if_missing:
                return int(existing["context_generation"]), False

            generation = int(existing["context_generation"]) if existing else 0
            usage_json = existing["current_usage_json"] if existing else None
            if current_usage is not None:
                usage_json = json.dumps(
                    current_usage,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            if reset_context:
                generation += 1
                previous = json.loads(usage_json) if usage_json else {}
                previous_context = previous.get("context_usage") or {}
                usage_json = json.dumps(
                    {
                        "usage": None,
                        "context_usage": {
                            "estimated_tokens": 0,
                            "max_input_length": int(
                                previous_context.get("max_input_length", 0)
                                or 0,
                            ),
                            "context_usage_ratio": 0,
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            self._conn.execute(
                "INSERT INTO session_runtime("
                "session_id, context_generation, state_json, "
                "current_usage_json, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "context_generation = excluded.context_generation, "
                "state_json = excluded.state_json, "
                "current_usage_json = excluded.current_usage_json, "
                "updated_at = excluded.updated_at",
                (
                    session_id,
                    generation,
                    state_json,
                    usage_json,
                    timestamp,
                ),
            )
            return generation, True

    def replace_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        state: dict[str, Any],
        context_generation: int,
        current_usage: dict[str, Any] | None,
    ) -> None:
        """Replace a runtime snapshot while preserving its generation."""
        with self._transaction():
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, user_id, channel) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (session_id, user_id, channel),
            )
            session = self._session_row(session_id)
            if session is None:
                raise RuntimeError("failed to create transcript session")
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            self._conn.execute(
                "INSERT INTO session_runtime("
                "session_id, context_generation, state_json, "
                "current_usage_json, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "context_generation = excluded.context_generation, "
                "state_json = excluded.state_json, "
                "current_usage_json = excluded.current_usage_json, "
                "updated_at = excluded.updated_at",
                (
                    session_id,
                    context_generation,
                    json.dumps(
                        state,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    (
                        json.dumps(
                            current_usage,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        if current_usage is not None
                        else None
                    ),
                    _utc_now(),
                ),
            )

    def update_runtime_state(
        self,
        *,
        session_id: str,
        path: list[str],
        value: Any,
    ) -> None:
        """Update one nested value in an existing runtime snapshot."""
        with self._transaction():
            row = self._conn.execute(
                "SELECT state_json FROM session_runtime "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            state = json.loads(row["state_json"])
            current = state
            for key in path[:-1]:
                child = current.get(key)
                if not isinstance(child, dict):
                    child = {}
                    current[key] = child
                current = child
            current[path[-1]] = value
            state_json = json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self._conn.execute(
                "UPDATE session_runtime SET state_json = ?, updated_at = ? "
                "WHERE session_id = ?",
                (state_json, _utc_now(), session_id),
            )

    def set_current_usage(
        self,
        *,
        session_id: str,
        usage: dict[str, Any] | None,
        context_usage: dict[str, Any] | None,
    ) -> None:
        """Persist the current context projection independently of history."""
        payload = json.dumps(
            {"usage": usage, "context_usage": context_usage},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._transaction():
            cursor = self._conn.execute(
                "UPDATE session_runtime SET current_usage_json = ?, "
                "updated_at = ? WHERE session_id = ?",
                (payload, _utc_now(), session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(session_id)

    def export_database(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bytes:
        """Return a consistent database snapshot without running turns."""
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "session.db"
            snapshot = sqlite3.connect(str(snapshot_path))
            snapshot.row_factory = sqlite3.Row
            snapshot.execute("PRAGMA foreign_keys=ON")
            try:
                with self._lock:
                    session = self._session_row(session_id)
                    if session is None:
                        raise KeyError(session_id)
                    self._assert_identity(
                        session,
                        user_id=user_id,
                        channel=channel,
                    )
                    self._conn.backup(snapshot)
                with snapshot:
                    snapshot.execute(
                        "DELETE FROM transcript_turns "
                        "WHERE session_id = ? AND status = 'running'",
                        (session_id,),
                    )
                    snapshot.execute(
                        "UPDATE transcript_sessions SET next_turn_seq = "
                        "COALESCE((SELECT MAX(turn_seq) + 1 "
                        "FROM transcript_turns WHERE session_id = ?), 1) "
                        "WHERE session_id = ?",
                        (session_id, session_id),
                    )
                integrity = snapshot.execute(
                    "PRAGMA integrity_check",
                ).fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "checkpoint database integrity check failed",
                    )
            finally:
                snapshot.close()
            return snapshot_path.read_bytes()

    def restore_database(
        self,
        blob: bytes,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> None:
        """Restore a database snapshot and retain active command turns."""
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "session.db"
            snapshot_path.write_bytes(blob)
            source = sqlite3.connect(str(snapshot_path))
            source.row_factory = sqlite3.Row
            source.execute("PRAGMA query_only=ON")
            try:
                integrity = source.execute(
                    "PRAGMA integrity_check",
                ).fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "checkpoint database integrity check failed",
                    )
                session = self._session_row(session_id, source)
                if session is None:
                    raise KeyError(session_id)
                self._assert_identity(
                    session,
                    user_id=user_id,
                    channel=channel,
                )
                with self._lock:
                    running_turns = self._conn.execute(
                        "SELECT session_id, turn_seq, turn_id, status, "
                        "error_json, replaces_turn_id, created_at, "
                        "finished_at FROM transcript_turns "
                        "WHERE session_id = ? AND status = 'running'",
                        (session_id,),
                    ).fetchall()
                    running_messages = self._conn.execute(
                        "SELECT m.session_id, m.turn_id, m.message_id, "
                        "m.ordinal, m.role, m.payload_json, "
                        "m.client_message_id, m.superseded_at, "
                        "m.created_at, m.finished_at "
                        "FROM transcript_messages AS m "
                        "JOIN transcript_turns AS t "
                        "ON t.session_id = m.session_id "
                        "AND t.turn_id = m.turn_id "
                        "WHERE m.session_id = ? AND t.status = 'running'",
                        (session_id,),
                    ).fetchall()
                    source.backup(self._conn)
                    with self._conn:
                        row = self._conn.execute(
                            "SELECT COALESCE(MAX(turn_seq), 0) "
                            "FROM transcript_turns WHERE session_id = ?",
                            (session_id,),
                        ).fetchone()
                        next_turn_seq = int(row[0]) + 1
                        restored_turns = [
                            (
                                turn["session_id"],
                                next_turn_seq + index,
                                turn["turn_id"],
                                turn["status"],
                                turn["error_json"],
                                turn["replaces_turn_id"],
                                turn["created_at"],
                                turn["finished_at"],
                            )
                            for index, turn in enumerate(running_turns)
                        ]
                        self._conn.executemany(
                            "INSERT INTO transcript_turns("
                            "session_id, turn_seq, turn_id, status, "
                            "error_json, replaces_turn_id, created_at, "
                            "finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            restored_turns,
                        )
                        self._conn.executemany(
                            "INSERT INTO transcript_messages("
                            "session_id, turn_id, message_id, ordinal, role, "
                            "payload_json, client_message_id, "
                            "superseded_at, created_at, finished_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [tuple(row) for row in running_messages],
                        )
                        self._conn.execute(
                            "UPDATE transcript_sessions SET next_turn_seq = "
                            "COALESCE((SELECT MAX(turn_seq) + 1 "
                            "FROM transcript_turns WHERE session_id = ?), 1) "
                            "WHERE session_id = ?",
                            (session_id, session_id),
                        )
            finally:
                source.close()

    def clone_completed_session_from(
        self,
        *,
        source_path: Path,
        source_session_id: str,
        target_session_id: str,
        target_user_id: str,
        target_channel: str,
    ) -> bool:
        """Clone persisted chat history and agent context into this store."""
        if self._session_row(target_session_id) is not None:
            raise ValueError("target transcript session already exists")

        self._conn.execute("ATTACH DATABASE ? AS parent", (str(source_path),))
        try:
            source = self._conn.execute(
                "SELECT next_turn_seq FROM parent.transcript_sessions "
                "WHERE session_id = ?",
                (source_session_id,),
            ).fetchone()
            if source is None:
                return False

            runtime = self._conn.execute(
                "SELECT context_generation, state_json, "
                "current_usage_json, updated_at "
                "FROM parent.session_runtime WHERE session_id = ?",
                (source_session_id,),
            ).fetchone()
            with self._transaction():
                self._conn.execute(
                    "INSERT INTO transcript_sessions("
                    "session_id, user_id, channel, next_turn_seq) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        target_session_id,
                        target_user_id,
                        target_channel,
                        int(source["next_turn_seq"]),
                    ),
                )
                self._conn.execute(
                    "INSERT INTO transcript_turns("
                    "session_id, turn_seq, turn_id, status, error_json, "
                    "replaces_turn_id, created_at, finished_at) "
                    "SELECT ?, turn_seq, turn_id, status, error_json, "
                    "replaces_turn_id, created_at, finished_at "
                    "FROM parent.transcript_turns "
                    "WHERE session_id = ? AND status != 'running'",
                    (target_session_id, source_session_id),
                )
                self._conn.execute(
                    "INSERT INTO transcript_messages("
                    "session_id, turn_id, message_id, ordinal, role, "
                    "payload_json, client_message_id, superseded_at, "
                    "created_at, finished_at) "
                    "SELECT ?, m.turn_id, m.message_id, m.ordinal, m.role, "
                    "m.payload_json, m.client_message_id, m.superseded_at, "
                    "m.created_at, m.finished_at "
                    "FROM parent.transcript_messages AS m "
                    "JOIN parent.transcript_turns AS t "
                    "ON t.session_id = m.session_id "
                    "AND t.turn_id = m.turn_id "
                    "WHERE m.session_id = ? AND t.status != 'running'",
                    (target_session_id, source_session_id),
                )
                if runtime is not None:
                    source_state = json.loads(runtime["state_json"])
                    state = (
                        {"agent": source_state["agent"]}
                        if "agent" in source_state
                        else {}
                    )
                    self._conn.execute(
                        "INSERT INTO session_runtime("
                        "session_id, context_generation, state_json, "
                        "current_usage_json, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            target_session_id,
                            int(runtime["context_generation"]),
                            json.dumps(
                                state,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            runtime["current_usage_json"],
                            runtime["updated_at"],
                        ),
                    )
            return True
        finally:
            self._conn.execute("DETACH DATABASE parent")

    def message_payloads(
        self,
        *,
        session_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Return visible persisted messages within an inclusive date range."""
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT payload_json, created_at "
                "FROM transcript_messages WHERE session_id = ? "
                "AND superseded_at IS NULL "
                "AND substr(created_at, 1, 10) BETWEEN ? AND ? "
                "ORDER BY created_at, ordinal",
                (session_id, start_date, end_date),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                continue
            if not payload.get("created_at") and not payload.get("timestamp"):
                payload["created_at"] = row["created_at"]
            messages.append(payload)
        return messages

    def recover_running_turns(self) -> int:
        """Cancel turns left running by a previous process."""
        with self._lock:
            orphan = self._conn.execute(
                "SELECT 1 FROM transcript_turns WHERE status = 'running' "
                "LIMIT 1",
            ).fetchone()
            if orphan is None:
                return 0
            with self._transaction():
                cursor = self._conn.execute(
                    "UPDATE transcript_turns SET status = 'cancelled', "
                    "finished_at = COALESCE(finished_at, ?) "
                    "WHERE status = 'running'",
                    (_utc_now(),),
                )
                return cursor.rowcount

    def import_legacy_messages(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        messages: list[Message],
    ) -> bool:
        """Atomically seed an empty transcript from legacy display history."""
        if not messages:
            return False
        turns: list[list[Message]] = []
        for message in messages:
            if not turns or _enum_value(message.role) == "user":
                turns.append([])
            turns[-1].append(message)

        now = _utc_now()
        with self._transaction():
            session = self._session_row(session_id)
            if session is not None:
                self._assert_identity(
                    session,
                    user_id=user_id,
                    channel=channel,
                )
                existing_turn = self._conn.execute(
                    "SELECT 1 FROM transcript_turns WHERE session_id = ? "
                    "LIMIT 1",
                    (session_id,),
                ).fetchone()
                if existing_turn is not None:
                    return False
                self._conn.execute(
                    "UPDATE transcript_sessions SET next_turn_seq = ? "
                    "WHERE session_id = ?",
                    (len(turns) + 1, session_id),
                )
            else:
                self._conn.execute(
                    "INSERT INTO transcript_sessions("
                    "session_id, user_id, channel, next_turn_seq) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, user_id, channel, len(turns) + 1),
                )
            for turn_seq, turn_messages in enumerate(turns, start=1):
                first_metadata = turn_messages[0].metadata or {}
                last_metadata = turn_messages[-1].metadata or {}
                created_at = str(first_metadata.get("timestamp") or now)
                finished_at = str(
                    last_metadata.get("finished_at")
                    or last_metadata.get("timestamp")
                    or created_at,
                )
                turn_id = f"legacy:{turn_seq}"
                self._conn.execute(
                    "INSERT INTO transcript_turns("
                    "session_id, turn_seq, turn_id, status, created_at, "
                    "finished_at) VALUES (?, ?, ?, 'completed', ?, ?)",
                    (
                        session_id,
                        turn_seq,
                        turn_id,
                        created_at,
                        finished_at,
                    ),
                )
                for ordinal, message in enumerate(turn_messages):
                    metadata = message.metadata or {}
                    self._conn.execute(
                        "INSERT INTO transcript_messages("
                        "session_id, turn_id, message_id, ordinal, role, "
                        "payload_json, created_at, client_message_id, "
                        "finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            turn_id,
                            message.id,
                            ordinal,
                            _enum_value(message.role),
                            message.model_dump_json(),
                            str(metadata.get("timestamp") or created_at),
                            self._client_message_id(message),
                            metadata.get("finished_at"),
                        ),
                    )
        return True

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
            if session is None:
                raise RuntimeError("failed to create transcript session")
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
        limit: int = 20,
        max_bytes: int = _DEFAULT_PAGE_MAX_BYTES,
    ) -> TranscriptPage | None:
        """Read a byte-bounded page without replaying active outputs."""
        if limit < 1 or limit > 100:
            raise ValueError(
                "transcript turn limit must be between 1 and 100",
            )
        if max_bytes < 1:
            raise ValueError("transcript page max_bytes must be positive")
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
            )
            turn_sql = "SELECT t.turn_seq FROM transcript_turns t "
            turn_sql += "WHERE t.session_id = ? "
            params: list[Any] = [session_id]
            if before is not None:
                operator = "<" if before.ordinal == 0 else "<="
                turn_sql += f"AND t.turn_seq {operator} ? "
                params.append(before.turn_seq)
            turn_sql += (
                "AND EXISTS (SELECT 1 FROM transcript_messages vm "
                "WHERE vm.session_id = t.session_id "
                "AND vm.turn_id = t.turn_id "
                "AND vm.superseded_at IS NULL "
                "AND (t.status != 'running' OR vm.role = 'user')) "
                "ORDER BY t.turn_seq DESC LIMIT ?"
            )
            params.append(limit + 1)
            candidates = connection.execute(turn_sql, params).fetchall()
            selected_turns = [
                int(row["turn_seq"]) for row in candidates[:limit]
            ]
            if not selected_turns:
                return TranscriptPage(
                    messages=[],
                    next_before=None,
                    has_more=False,
                )

            placeholders = ",".join("?" for _ in selected_turns)
            message_filter = (
                "FROM transcript_turns t CROSS JOIN transcript_messages m "
                "ON m.session_id = t.session_id AND m.turn_id = t.turn_id "
                "WHERE t.session_id = ? AND m.superseded_at IS NULL "
                "AND (t.status != 'running' OR m.role = 'user') "
                f"AND t.turn_seq IN ({placeholders}) "
            )
            message_params: list[Any] = [session_id, *selected_turns]
            if before is not None and before.ordinal > 0:
                message_filter += "AND (t.turn_seq < ? OR "
                message_filter += "(t.turn_seq = ? AND m.ordinal < ?)) "
                message_params.extend(
                    [before.turn_seq, before.turn_seq, before.ordinal],
                )

            size_sql = (
                "SELECT t.turn_seq, m.ordinal, "
                "length(CAST(m.payload_json AS BLOB)) AS payload_bytes "
                + message_filter
                + "ORDER BY t.turn_seq DESC, m.ordinal DESC"
            )
            selected_count = 0
            payload_bytes = 0
            oldest_position: TranscriptCursor | None = None
            has_more = len(candidates) > limit
            for row in connection.execute(size_sql, message_params):
                message_bytes = int(row["payload_bytes"])
                exceeds_limit = payload_bytes + message_bytes > max_bytes
                if selected_count and exceeds_limit:
                    has_more = True
                    break
                selected_count += 1
                payload_bytes += message_bytes
                oldest_position = TranscriptCursor(
                    turn_seq=int(row["turn_seq"]),
                    ordinal=int(row["ordinal"]),
                )

            if selected_count == 0:
                return TranscriptPage(
                    messages=[],
                    next_before=None,
                    has_more=False,
                )

            message_sql = (
                "SELECT m.payload_json, "
                "m.created_at AS message_created_at, "
                "m.finished_at AS message_finished_at, m.ordinal, "
                "t.turn_id, t.turn_seq, t.status AS turn_status, "
                "t.error_json, t.finished_at AS turn_finished_at "
                + message_filter
                + "ORDER BY t.turn_seq DESC, m.ordinal DESC LIMIT ?"
            )
            rows = connection.execute(
                message_sql,
                [*message_params, selected_count],
            ).fetchall()
            rows.reverse()
            return TranscriptPage(
                messages=[self._message_from_row(row) for row in rows],
                next_before=oldest_position if has_more else None,
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


__all__ = [
    "RuntimeSnapshot",
    "TranscriptCursor",
    "TranscriptPage",
    "TranscriptStore",
]
