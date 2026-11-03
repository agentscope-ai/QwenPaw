# -*- coding: utf-8 -*-
"""Durable, display-faithful chat transcript storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, cast
from uuid import uuid4

from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ...schemas import Message, TextContent
from ...token_usage.turn_usage import TURN_USAGE_META_KEY
from .context_revisions import (
    commit_turn_revision,
    read_revision_state,
    record_revision,
)
from .event_schema import advance_projection_watermark
from .event_store import ConversationEventStore, EventDraft
from .transcript_blocks import (
    message_envelope,
    write_message_blocks,
    write_message_envelope,
)
from .transcript_schema import initialize_database, validate_database
from .transcript_models import (
    RuntimeSnapshot,
    TranscriptCursor,
    TranscriptPage,
    TranscriptUserMessage,
    TranscriptUserMessagePage,
)
from .transcript_paging import TranscriptPageBuilder
from .projection_rebuild import rebuild_projections

_BUSY_TIMEOUT_MS = 5000
TurnStatus = Literal["running", "completed", "failed", "cancelled"]
_DEFAULT_PAGE_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_PAGE_MAX_CONTENT_BLOCKS = 40
_VISIBLE_TURN_AT_SNAPSHOT = (
    "NOT EXISTS (SELECT 1 FROM transcript_turns replacement "
    "JOIN event_log terminal ON terminal.turn_id = replacement.turn_id "
    "WHERE replacement.session_id = t.session_id "
    "AND replacement.replaces_turn_id = t.turn_id "
    "AND terminal.event_type = 'turn.completed' AND terminal.seq <= ?) "
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _content_hash(codec: str, payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(codec.encode("utf-8"))
    digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()


# pylint: disable=too-many-public-methods
class TranscriptStore:
    """Workspace-owned SQLite store for user-visible chat transcripts."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        storage_id: str | None = None,
        create: bool = True,
    ) -> None:
        self._path = Path(db_path).expanduser()
        self._storage_id = storage_id or self._path.stem
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        uri = self._path.resolve().as_uri() + (
            "?mode=rwc" if create else "?mode=rw"
        )
        self._conn = sqlite3.connect(
            uri,
            uri=True,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        try:
            initialize_database(self._conn)
            self._conn.execute("PRAGMA journal_mode=WAL")
            if storage_id is None:
                row = self._conn.execute(
                    "SELECT storage_id FROM transcript_sessions LIMIT 1",
                ).fetchone()
                if row is not None:
                    self._storage_id = str(row[0])
        except BaseException:
            self._conn.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        """Return the database path owned by this store."""
        return self._path

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
            if self._conn.in_transaction:
                yield
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _write_fact_object(self, *, codec: str, value: Any) -> str:
        payload = _canonical_json(value).encode("utf-8")
        content_hash = _content_hash(codec, payload)
        self._conn.execute(
            "INSERT OR IGNORE INTO content_objects("
            "content_hash, codec, payload, byte_length) "
            "VALUES (?, ?, ?, ?)",
            (content_hash, codec, payload, len(payload)),
        )
        return content_hash

    def _append_fact(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        recorded_at: str,
        turn_id: str | None = None,
        message_id: str | None = None,
        block_id: str | None = None,
    ) -> int:
        payload_json = _canonical_json(payload)
        envelope = {
            "block_id": block_id,
            "event_type": event_type,
            "message_id": message_id,
            "payload": payload,
            "payload_version": 1,
            "turn_id": turn_id,
        }
        payload_hash = hashlib.sha256(
            _canonical_json(envelope).encode("utf-8"),
        ).hexdigest()
        cursor = self._conn.execute(
            "INSERT INTO event_log("
            "event_id, event_type, payload_version, turn_id, message_id, "
            "block_id, payload_json, payload_hash, idempotency_key, "
            "recorded_at) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(idempotency_key) DO NOTHING",
            (
                uuid4().hex,
                event_type,
                turn_id,
                message_id,
                block_id,
                payload_json,
                payload_hash,
                idempotency_key,
                recorded_at,
            ),
        )
        if cursor.rowcount == 1:
            if cursor.lastrowid is None:
                raise RuntimeError("event append returned no sequence")
            event_seq = int(cursor.lastrowid)
            advance_projection_watermark(
                self._conn,
                event_seq,
                updated_at=recorded_at,
            )
            return event_seq
        row = self._conn.execute(
            "SELECT seq, payload_hash FROM event_log "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None or row["payload_hash"] != payload_hash:
            raise ValueError("event idempotency conflict")
        event_seq = int(row["seq"])
        advance_projection_watermark(
            self._conn,
            event_seq,
            updated_at=recorded_at,
        )
        return event_seq

    def read_provider_state(self, *, session_id: str) -> dict[str, Any]:
        """Read external identities directly from immutable provider facts."""
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT event_type, turn_id, payload_json FROM event_log "
                "WHERE event_type IN "
                "('provider.session_bound', 'provider.turn_boundary') "
                "ORDER BY seq",
            ).fetchall()
            completed = {
                str(row[0])
                for row in connection.execute(
                    "SELECT turn_id FROM transcript_turns "
                    "WHERE session_id = ? AND status = 'completed'",
                    (session_id,),
                )
            }
            has_history = (
                connection.execute(
                    "SELECT 1 FROM transcript_turns WHERE session_id = ? "
                    "AND status = 'completed' LIMIT 1",
                    (session_id,),
                ).fetchone()
                is not None
            )
        binding = None
        boundaries = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            if row["event_type"] == "provider.session_bound":
                binding = payload
            elif row["turn_id"] in completed:
                boundaries[str(row["turn_id"])] = payload
        return {
            "binding": binding,
            "boundaries": boundaries,
            "has_history": has_history,
        }

    def read_legacy_turn_blocks(self, *, session_id: str) -> dict:
        """Read completed imported turns for exact provider matching."""
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT t.turn_id, m.role, b.payload_json "
                "FROM transcript_turns t "
                "JOIN transcript_messages m ON m.session_id=t.session_id "
                "AND m.turn_id=t.turn_id "
                "JOIN transcript_blocks b ON b.session_id=m.session_id "
                "AND b.message_id=m.message_id "
                "WHERE t.session_id=? AND t.status='completed' "
                "AND t.turn_id LIKE 'legacy:%' "
                "AND m.superseded_at IS NULL "
                "ORDER BY t.turn_seq, m.ordinal, b.ordinal",
                (session_id,),
            ).fetchall()
        turns = {}
        for row in rows:
            turns.setdefault(row["turn_id"], []).append(
                (row["role"], json.loads(row["payload_json"])),
            )
        return turns

    def record_provider_fact(
        self,
        *,
        session_id: str,
        kind: str,
        data: dict[str, Any],
        turn_id: str | None = None,
    ) -> None:
        """Append a provider identity or exact fork boundary."""
        if kind not in {"session_bound", "turn_boundary"}:
            raise ValueError("invalid provider fact kind")
        with self._transaction():
            self._append_fact(
                event_type=f"provider.{kind}",
                payload=data,
                idempotency_key=(
                    f"provider:boundary:{turn_id}"
                    if kind == "turn_boundary"
                    else uuid4().hex
                ),
                recorded_at=_utc_now(),
                turn_id=turn_id,
            )

    def _append_session_fact(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        recorded_at: str,
    ) -> None:
        self._append_fact(
            event_type="session.created",
            payload={
                "channel": channel,
                "session_id": session_id,
                "storage_id": self._storage_id,
                "user_id": user_id,
            },
            idempotency_key="session:created",
            recorded_at=recorded_at,
        )

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
        storage_id: str | None = None,
    ) -> None:
        if (
            row["user_id"] != user_id
            or row["channel"] != channel
            or (storage_id is not None and row["storage_id"] != storage_id)
        ):
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
                storage_id=self._storage_id,
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
                storage_id=self._storage_id,
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

    def read_current_usage(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> tuple[int, dict[str, Any] | None] | None:
        """Read context usage without decoding the runtime state."""
        with self._read_connection() as connection:
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            row = connection.execute(
                "SELECT context_generation, current_usage_json "
                "FROM session_runtime WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            usage = (
                json.loads(row["current_usage_json"])
                if row["current_usage_json"]
                else None
            )
            return int(row["context_generation"]), usage

    def read_turn_context(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        turn_id: str,
    ) -> RuntimeSnapshot | None:
        """Read the exact committed context; legacy turns have no revision."""
        with self._read_connection() as connection:
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            row = connection.execute(
                "SELECT r.revision_id, r.context_generation, "
                "COALESCE(u.usage_json, r.current_usage_json) "
                "AS current_usage_json FROM turn_context_revision t "
                "JOIN context_revisions r ON r.session_id = t.session_id "
                "AND r.revision_id = t.revision_id "
                "LEFT JOIN projection_turn_usage u "
                "ON u.session_id = t.session_id "
                "AND u.turn_id = t.turn_id "
                "WHERE t.session_id = ? AND t.turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if row is None:
                return None
            return RuntimeSnapshot(
                state=read_revision_state(
                    connection,
                    session_id=session_id,
                    revision_id=str(row["revision_id"]),
                ),
                context_generation=int(row["context_generation"]),
                current_usage=(
                    json.loads(row["current_usage_json"])
                    if row["current_usage_json"]
                    else None
                ),
            )

    def _ensure_migration_anchor(
        self,
        *,
        session_id: str,
        state: dict[str, Any],
        generation: int,
        usage_json: str | None,
        created_at: str,
    ) -> None:
        latest = self._conn.execute(
            "SELECT turn_id FROM transcript_turns "
            "WHERE session_id = ? AND status != 'running' "
            "ORDER BY turn_seq DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if latest is None:
            return
        bound = self._conn.execute(
            "SELECT 1 FROM turn_context_revision "
            "WHERE session_id = ? AND turn_id = ?",
            (session_id, latest[0]),
        ).fetchone()
        if bound is not None:
            return
        record_revision(
            self._conn,
            session_id=session_id,
            turn_id=str(latest[0]),
            state=state,
            generation=generation,
            usage_json=usage_json,
            created_at=created_at,
            kind="migration_anchor",
        )

    def record_legacy_migration(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        complete: bool = False,
    ) -> bool:
        """Persist migration ownership and its final completion boundary."""
        with self._transaction():
            row = self._conn.execute(
                "SELECT payload_json FROM event_log "
                "WHERE idempotency_key = ?",
                (f"migration:started:{session_id}",),
            ).fetchone()
            restore_runtime = (
                json.loads(row[0])["restore_runtime"]
                if row
                else self._conn.execute(
                    "SELECT 1 FROM session_runtime WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                is None
            )
            stage = "completed" if complete else "started"
            self._append_fact(
                event_type=f"migration.{stage}",
                payload={"restore_runtime": restore_runtime},
                idempotency_key=f"migration:{stage}:{session_id}",
                recorded_at=_utc_now(),
            )
            return restore_runtime

    def write_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        state: dict[str, Any],
        current_usage: dict[str, Any] | None = None,
        reset_context: bool = False,
        reset_provider: str | None = None,
        only_if_missing: bool = False,
        turn_id: str | None = None,
        migration_anchor: bool = False,
        migration_approximate: bool = False,
        context_generation: int | None = None,
        exact_current_usage: bool = False,
        legacy_import: bool = False,
    ) -> tuple[int, bool]:
        """Persist one runtime snapshot and optionally start a new context."""
        state_json = _canonical_json(state)
        timestamp = _utc_now()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, storage_id, user_id, channel) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO NOTHING",
                (session_id, self._storage_id, user_id, channel),
            )
            session = self._session_row(session_id)
            if session is None:
                raise RuntimeError("failed to create transcript session")
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            self._append_session_fact(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                recorded_at=timestamp,
            )
            existing = self._conn.execute(
                "SELECT context_generation, current_usage_json "
                "FROM session_runtime WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is not None and legacy_import:
                revision = self._conn.execute(
                    "SELECT r.kind FROM current_context_revision c "
                    "JOIN context_revisions r ON r.session_id = c.session_id "
                    "AND r.revision_id = c.revision_id "
                    "WHERE c.session_id = ?",
                    (session_id,),
                ).fetchone()
                if revision is None or revision[0] != "migration_approximate":
                    return int(existing["context_generation"]), False
            if existing is not None and only_if_missing:
                if migration_anchor:
                    self._ensure_migration_anchor(
                        session_id=session_id,
                        state=json.loads(
                            self._conn.execute(
                                "SELECT state_json FROM session_runtime "
                                "WHERE session_id = ?",
                                (session_id,),
                            ).fetchone()[0],
                        ),
                        generation=int(existing["context_generation"]),
                        usage_json=existing["current_usage_json"],
                        created_at=timestamp,
                    )
                return int(existing["context_generation"]), False

            generation = int(existing["context_generation"]) if existing else 0
            if context_generation is not None:
                generation = context_generation
            usage_json = existing["current_usage_json"] if existing else None
            if current_usage is not None or exact_current_usage:
                usage_json = (
                    _canonical_json(current_usage)
                    if current_usage is not None
                    else None
                )
            if reset_context:
                generation += 1
                previous = json.loads(usage_json) if usage_json else {}
                previous_context = previous.get("context_usage") or {}
                usage_json = _canonical_json(
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
            if migration_anchor and turn_id is None:
                latest = self._conn.execute(
                    "SELECT turn_id FROM transcript_turns "
                    "WHERE session_id = ? AND status != 'running' "
                    "ORDER BY turn_seq DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                turn_id = str(latest[0]) if latest else None
            revision_id = record_revision(
                self._conn,
                session_id=session_id,
                turn_id=turn_id,
                state=state,
                generation=generation,
                usage_json=usage_json,
                created_at=timestamp,
                kind=(
                    "migration_approximate"
                    if migration_approximate
                    else (
                        "migration_anchor"
                        if migration_anchor
                        else (
                            "clear"
                            if reset_context
                            else (
                                "turn_commit"
                                if turn_id is not None
                                else "snapshot"
                            )
                        )
                    )
                ),
            )
            reason = "turn_commit" if turn_id is not None else "snapshot"
            if reset_context:
                reason = "clear"
            elif migration_approximate:
                reason = "migration_approximate"
            elif migration_anchor:
                reason = "migration"
            self._append_fact(
                event_type="runtime.committed",
                payload={
                    "generation": generation,
                    "reason": reason,
                    "revision_id": revision_id,
                },
                idempotency_key=f"runtime:{revision_id}",
                recorded_at=timestamp,
                turn_id=turn_id,
            )
            if reset_provider is not None:
                self._append_fact(
                    event_type="provider.session_bound",
                    payload={
                        "provider": reset_provider,
                        "external_session_id": None,
                    },
                    idempotency_key=uuid4().hex,
                    recorded_at=timestamp,
                    turn_id=turn_id,
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
        timestamp = _utc_now()
        usage_json = (
            _canonical_json(current_usage)
            if current_usage is not None
            else None
        )
        with self._transaction():
            self._conn.execute(
                "INSERT INTO transcript_sessions("
                "session_id, storage_id, user_id, channel) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (session_id, self._storage_id, user_id, channel),
            )
            session = self._session_row(session_id)
            if session is None:
                raise RuntimeError("failed to create transcript session")
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            self._append_session_fact(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                recorded_at=timestamp,
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
                    _canonical_json(state),
                    (usage_json),
                    timestamp,
                ),
            )
            revision_id = record_revision(
                self._conn,
                session_id=session_id,
                turn_id=None,
                state=state,
                generation=context_generation,
                usage_json=usage_json,
                created_at=timestamp,
                kind="restore",
            )
            self._append_fact(
                event_type="runtime.committed",
                payload={
                    "generation": context_generation,
                    "reason": "restore",
                    "revision_id": revision_id,
                },
                idempotency_key=f"runtime:{revision_id}",
                recorded_at=timestamp,
            )

    def update_runtime_state(
        self,
        *,
        session_id: str,
        path: list[str],
        value: Any,
        delete: bool = False,
    ) -> None:
        """Update one nested value in an existing runtime snapshot."""
        with self._transaction():
            row = self._conn.execute(
                "SELECT state_json, context_generation, current_usage_json "
                "FROM session_runtime "
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
                    if delete:
                        return
                    child = {}
                    current[key] = child
                current = child
            if delete:
                current.pop(path[-1], None)
            else:
                current[path[-1]] = value
            state_json = _canonical_json(state)
            timestamp = _utc_now()
            self._conn.execute(
                "UPDATE session_runtime SET state_json = ?, updated_at = ? "
                "WHERE session_id = ?",
                (state_json, timestamp, session_id),
            )
            revision_id = record_revision(
                self._conn,
                session_id=session_id,
                turn_id=None,
                state=state,
                generation=int(row["context_generation"]),
                usage_json=row["current_usage_json"],
                created_at=timestamp,
                kind="state_update",
            )
            self._append_fact(
                event_type="runtime.committed",
                payload={
                    "generation": int(row["context_generation"]),
                    "reason": "state_update",
                    "revision_id": revision_id,
                },
                idempotency_key=f"runtime:{revision_id}",
                recorded_at=timestamp,
            )

    def set_current_usage(
        self,
        *,
        session_id: str,
        usage: dict[str, Any] | None,
        context_usage: dict[str, Any] | None,
    ) -> None:
        """Persist the current context projection independently of history."""
        payload = _canonical_json(
            {"usage": usage, "context_usage": context_usage},
        )
        with self._transaction():
            row = self._conn.execute(
                "SELECT state_json, context_generation "
                "FROM session_runtime WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            timestamp = _utc_now()
            cursor = self._conn.execute(
                "UPDATE session_runtime SET current_usage_json = ?, "
                "updated_at = ? WHERE session_id = ?",
                (payload, timestamp, session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(session_id)
            revision_id = record_revision(
                self._conn,
                session_id=session_id,
                turn_id=None,
                state=json.loads(row["state_json"]),
                generation=int(row["context_generation"]),
                usage_json=payload,
                created_at=timestamp,
                kind="usage_update",
            )
            self._append_fact(
                event_type="runtime.committed",
                payload={
                    "generation": int(row["context_generation"]),
                    "reason": "usage_update",
                    "revision_id": revision_id,
                },
                idempotency_key=f"runtime:{revision_id}",
                recorded_at=timestamp,
            )

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
                        storage_id=self._storage_id,
                    )
                    self._conn.backup(snapshot)
                running_turn_ids = [
                    row[0]
                    for row in snapshot.execute(
                        "SELECT turn_id FROM transcript_turns "
                        "WHERE session_id = ? AND status = 'running'",
                        (session_id,),
                    )
                ]
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
            events = ConversationEventStore(snapshot_path)
            try:
                for turn_id in running_turn_ids:
                    events.append(
                        EventDraft(
                            event_type="turn.excluded",
                            payload={},
                            turn_id=turn_id,
                            idempotency_key=f"checkpoint:exclude:{turn_id}",
                        ),
                    )
            finally:
                events.close()
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
                validate_database(source)
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
                    storage_id=self._storage_id,
                )
                with self._lock:
                    running_turns = self._conn.execute(
                        "SELECT session_id, turn_seq, turn_id, status, "
                        "error_json, replaces_turn_id, created_at, "
                        "finished_at FROM transcript_turns "
                        "WHERE session_id = ? AND status = 'running'",
                        (session_id,),
                    ).fetchall()
                    restored = TranscriptStore(
                        snapshot_path,
                        storage_id=self._storage_id,
                    )
                    try:
                        for turn in running_turns:
                            restored._fork_copy_turn(
                                self._conn,
                                turn,
                                source_session_id=session_id,
                                target_session_id=session_id,
                                target_user_id=user_id,
                                target_channel=channel,
                                native_context=True,
                                restore_active=True,
                            )
                        restored._conn.backup(self._conn)
                    finally:
                        restored.close()
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

        source = sqlite3.connect(
            source_path.resolve().as_uri() + "?mode=ro",
            uri=True,
        )
        source.row_factory = sqlite3.Row
        try:
            source.execute("BEGIN")
            if self._session_row(source_session_id, source) is None:
                return False
            with self._transaction():
                self._conn.execute(
                    "INSERT INTO transcript_sessions("
                    "session_id, storage_id, user_id, channel) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        target_session_id,
                        self._storage_id,
                        target_user_id,
                        target_channel,
                    ),
                )
                self._append_session_fact(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                    recorded_at=_utc_now(),
                )
            turns = source.execute(
                "SELECT * FROM transcript_turns WHERE session_id = ? "
                "AND status != 'running' ORDER BY turn_seq",
                (source_session_id,),
            ).fetchall()
            for turn in turns:
                self._fork_copy_turn(
                    source,
                    turn,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                    target_user_id=target_user_id,
                    target_channel=target_channel,
                    agent_only=True,
                )
            runtime = source.execute(
                "SELECT * FROM session_runtime WHERE session_id = ?",
                (source_session_id,),
            ).fetchone()
            if runtime is not None:
                state = json.loads(runtime["state_json"])
                self.write_runtime_state(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                    state=self._fork_runtime_state(
                        {"agent": state["agent"]} if "agent" in state else {},
                        source_session_id=source_session_id,
                        target_session_id=target_session_id,
                    ),
                    context_generation=int(runtime["context_generation"]),
                    current_usage=(
                        json.loads(runtime["current_usage_json"])
                        if runtime["current_usage_json"]
                        else None
                    ),
                    exact_current_usage=True,
                )
            from ...agents.context.scroll.history import HistoryStore

            history = HistoryStore(self._path)
            history.close()
            self._fork_copy_recall_events(
                source,
                source_session_id=source_session_id,
                target_session_id=target_session_id,
                through_event_seq=source.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM event_log",
                ).fetchone()[0],
            )
            self.rebuild_projections()
            return True
        finally:
            source.close()

    @staticmethod
    def _fork_history_session_id(
        value: str,
        *,
        source_session_id: str,
        target_session_id: str,
    ) -> str:
        """Retarget one Scroll history identity without changing generation."""
        if value == source_session_id:
            return target_session_id
        prefix = f"{source_session_id}\x1fcontext:"
        if value.startswith(prefix):
            return f"{target_session_id}{value[len(source_session_id):]}"
        return value

    @classmethod
    def _fork_runtime_state(
        cls,
        state: dict[str, Any],
        *,
        source_session_id: str,
        target_session_id: str,
    ) -> dict[str, Any]:
        """Retarget the session identity embedded in Scroll bookkeeping."""
        copied = json.loads(_canonical_json(state))
        agent = copied.get("agent")
        if not isinstance(agent, dict):
            return copied
        scroll = agent.get("scroll")
        if not isinstance(scroll, dict):
            return copied
        index = scroll.get("index")
        if isinstance(index, dict) and isinstance(
            index.get("session_id"),
            str,
        ):
            index["session_id"] = cls._fork_history_session_id(
                index["session_id"],
                source_session_id=source_session_id,
                target_session_id=target_session_id,
            )
        return copied

    def _fork_copy_turn(
        self,
        source: sqlite3.Connection,
        turn: sqlite3.Row,
        *,
        source_session_id: str,
        target_session_id: str,
        target_user_id: str,
        target_channel: str,
        native_context: bool = False,
        agent_only: bool = False,
        restore_active: bool = False,
    ) -> None:
        """Copy one materialized turn as new append-only target facts."""
        source_turn_id = str(turn["turn_id"])
        recorded_start = self._conn.execute(
            "SELECT 1 FROM event_log WHERE idempotency_key = ?",
            (f"turn:{source_turn_id}:started",),
        ).fetchone()
        self.start_turn(
            session_id=target_session_id,
            user_id=target_user_id,
            channel=target_channel,
            turn_id=source_turn_id,
            replaces_turn_id=turn["replaces_turn_id"],
            created_at=str(turn["created_at"]),
        )
        if restore_active and recorded_start:
            with self._transaction():
                restored_turn = self._conn.execute(
                    "SELECT turn_seq FROM transcript_turns "
                    "WHERE session_id = ? AND turn_id = ?",
                    (target_session_id, source_turn_id),
                ).fetchone()
                self._append_fact(
                    event_type="turn.started",
                    payload={
                        "created_at": str(turn["created_at"]),
                        "replaces_turn_id": turn["replaces_turn_id"],
                        "turn_seq": restored_turn[0],
                    },
                    idempotency_key=f"restore:turn:{uuid4().hex}",
                    recorded_at=_utc_now(),
                    turn_id=source_turn_id,
                )
        messages = source.execute(
            "SELECT payload_json FROM event_log "
            "WHERE event_type = 'message.committed' AND turn_id = ? "
            "ORDER BY seq",
            (source_turn_id,),
        ).fetchall()
        for event in messages:
            row = json.loads(event["payload_json"])
            envelope = json.loads(
                source.execute(
                    "SELECT payload FROM content_objects "
                    "WHERE content_hash = ?",
                    (row["envelope_ref"],),
                ).fetchone()[0],
            )
            envelope["content"] = [
                json.loads(
                    source.execute(
                        "SELECT payload FROM content_objects "
                        "WHERE content_hash = ?",
                        (ref,),
                    ).fetchone()[0],
                )
                for ref in row["block_refs"]
            ]
            message = Message.model_validate(envelope)
            metadata = message.metadata
            if metadata is not None and TURN_USAGE_META_KEY in metadata:
                metadata = dict(metadata)
                metadata.pop(TURN_USAGE_META_KEY)
            self.upsert_message(
                session_id=target_session_id,
                turn_id=source_turn_id,
                message=message.model_copy(update={"metadata": metadata}),
                ordinal=int(row["ordinal"]),
                created_at=str(row["created_at"]),
                finished_at=row["finished_at"],
                force_event=restore_active,
            )

        revision = source.execute(
            "SELECT r.revision_id, r.context_generation, "
            "COALESCE(u.usage_json, r.current_usage_json) "
            "AS current_usage_json "
            "FROM turn_context_revision t "
            "JOIN context_revisions r ON r.session_id = t.session_id "
            "AND r.revision_id = t.revision_id "
            "LEFT JOIN projection_turn_usage u "
            "ON u.session_id = t.session_id AND u.turn_id = t.turn_id "
            "WHERE t.session_id = ? AND t.turn_id = ?",
            (source_session_id, source_turn_id),
        ).fetchone()
        if revision is not None and not native_context:
            state = read_revision_state(
                source,
                session_id=source_session_id,
                revision_id=str(revision["revision_id"]),
            )
            if agent_only:
                state = {"agent": state["agent"]} if "agent" in state else {}
            usage_json = revision["current_usage_json"]
            self.write_runtime_state(
                session_id=target_session_id,
                user_id=target_user_id,
                channel=target_channel,
                state=self._fork_runtime_state(
                    state,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                ),
                current_usage=(json.loads(usage_json) if usage_json else None),
                turn_id=source_turn_id,
                context_generation=int(revision["context_generation"]),
                exact_current_usage=True,
            )

        if turn["status"] != "running":
            error = (
                json.loads(turn["error_json"]) if turn["error_json"] else None
            )
            self.finish_turn(
                session_id=target_session_id,
                turn_id=source_turn_id,
                status=cast(TurnStatus, str(turn["status"])),
                error=error,
                finished_at=turn["finished_at"],
            )
        usage = source.execute(
            "SELECT usage_json FROM projection_turn_usage "
            "WHERE session_id = ? AND turn_id = ?",
            (source_session_id, source_turn_id),
        ).fetchone()
        if usage is not None:
            snapshot = json.loads(usage["usage_json"])
            self.attach_turn_usage(
                session_id=target_session_id,
                turn_id=source_turn_id,
                usage=snapshot.get("usage"),
                context_usage=snapshot.get("context_usage"),
            )

    def _fork_copy_recall_events(
        self,
        source: sqlite3.Connection,
        *,
        source_session_id: str,
        target_session_id: str,
        through_event_seq: int,
        next_legacy_source_seq: int | None = None,
    ) -> None:
        """Copy Recall facts visible at the selected runtime boundary."""
        recall_events = source.execute(
            "SELECT event_type, payload_json, recorded_at "
            "FROM event_log WHERE seq <= ? AND event_type IN "
            "('recall.entry_committed', 'recall.entries_purged') "
            "ORDER BY seq",
            (through_event_seq,),
        ).fetchall()
        with self._transaction():
            for event in recall_events:
                payload = json.loads(event["payload_json"])
                if (
                    next_legacy_source_seq is not None
                    and event["event_type"] == "recall.entry_committed"
                    and int(payload.get("source_seq") or 0)
                    >= next_legacy_source_seq
                ):
                    continue
                ref_key = (
                    "entry_ref"
                    if event["event_type"] == "recall.entry_committed"
                    else "purge_ref"
                )
                source_object = source.execute(
                    "SELECT codec, payload FROM content_objects "
                    "WHERE content_hash = ?",
                    (payload[ref_key],),
                ).fetchone()
                if source_object is None:
                    raise ValueError("fork recall object is missing")
                value = json.loads(bytes(source_object["payload"]).decode())
                if ref_key == "entry_ref":
                    history_session_id = self._fork_history_session_id(
                        str(payload["history_session_id"]),
                        source_session_id=source_session_id,
                        target_session_id=target_session_id,
                    )
                    payload["history_session_id"] = history_session_id
                    value["session_id"] = history_session_id
                target_ref = self._write_fact_object(
                    codec=str(source_object["codec"]),
                    value=value,
                )
                payload[ref_key] = target_ref
                key = (
                    f"recall:{payload['history_session_id']}:"
                    f"{payload['source_seq']}:{target_ref}"
                    if ref_key == "entry_ref"
                    else f"recall:purge:{target_ref}"
                )
                self._append_fact(
                    event_type=str(event["event_type"]),
                    payload=payload,
                    idempotency_key=key,
                    recorded_at=str(event["recorded_at"]),
                )

    def fork_completed_turn_from(
        self,
        *,
        source_path: Path,
        source_session_id: str,
        source_chat_id: str,
        turn_id: str,
        target_session_id: str,
        target_user_id: str,
        target_channel: str,
        native_context: bool = False,
    ) -> int:
        """Rebuild an independent conversation through one completed turn."""
        if (
            self._conn.execute(
                "SELECT 1 FROM transcript_sessions LIMIT 1",
            ).fetchone()
            is not None
        ):
            raise ValueError("target transcript session already exists")

        uri = f"{source_path.resolve().as_uri()}?mode=ro"
        source = sqlite3.connect(uri, uri=True)
        source.row_factory = sqlite3.Row
        source.execute("PRAGMA query_only=ON")
        source.execute("BEGIN")
        try:
            source_session = source.execute(
                "SELECT storage_id FROM transcript_sessions "
                "WHERE session_id = ?",
                (source_session_id,),
            ).fetchone()
            if source_session is None:
                raise KeyError("source transcript session not found")
            boundary = source.execute(
                "SELECT turn_seq, status FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (source_session_id, turn_id),
            ).fetchone()
            if boundary is None:
                raise KeyError("fork turn not found")
            if boundary["status"] != "completed":
                raise ValueError("fork turn must be completed")
            turn_seq = int(boundary["turn_seq"])
            boundary_event = None
            if not native_context:
                boundary_revision = source.execute(
                    "SELECT r.revision_id FROM turn_context_revision t "
                    "JOIN context_revisions r "
                    "ON r.session_id = t.session_id "
                    "AND r.revision_id = t.revision_id "
                    "WHERE t.session_id = ? AND t.turn_id = ?",
                    (source_session_id, turn_id),
                ).fetchone()
                if boundary_revision is None:
                    raise ValueError("fork turn has no committed runtime")
                boundary_event = source.execute(
                    "SELECT seq FROM event_log "
                    "WHERE event_type = 'runtime.committed' "
                    "AND json_extract(payload_json, '$.revision_id') = ? "
                    "ORDER BY seq DESC LIMIT 1",
                    (boundary_revision["revision_id"],),
                ).fetchone()
                if boundary_event is None:
                    raise ValueError("fork runtime event is missing")
            next_legacy_source_seq = None
            if turn_id.startswith("legacy:"):
                next_legacy = source.execute(
                    "SELECT turn_id FROM transcript_turns "
                    "WHERE session_id = ? AND turn_seq > ? "
                    "AND turn_id LIKE 'legacy:%' "
                    "ORDER BY turn_seq LIMIT 1",
                    (source_session_id, turn_seq),
                ).fetchone()
                if next_legacy is not None:
                    next_row = source.execute(
                        "SELECT MIN(json_extract(payload_json, "
                        "'$.source_seq')) FROM event_log "
                        "WHERE event_type = 'recall.entry_committed' "
                        "AND turn_id = ?",
                        (next_legacy["turn_id"],),
                    ).fetchone()
                    if next_row[0] is not None:
                        next_legacy_source_seq = int(next_row[0])

            with self._transaction():
                timestamp = _utc_now()
                self._conn.execute(
                    "INSERT INTO transcript_sessions("
                    "session_id, storage_id, user_id, channel) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        target_session_id,
                        self._storage_id,
                        target_user_id,
                        target_channel,
                    ),
                )
                self._append_session_fact(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                    recorded_at=timestamp,
                )
                self._append_fact(
                    event_type="session.forked",
                    payload={
                        "source_chat_id": source_chat_id,
                        "source_session_id": source_session_id,
                        "source_storage_id": str(source_session["storage_id"]),
                        "turn_id": turn_id,
                        "turn_seq": turn_seq,
                    },
                    idempotency_key="session:forked",
                    recorded_at=timestamp,
                    turn_id=turn_id,
                )

            from ...agents.context.scroll.history import HistoryStore

            history = HistoryStore(self._path)
            history.close()

            turns = source.execute(
                "SELECT * FROM transcript_turns WHERE session_id = ? "
                "AND turn_seq <= ? ORDER BY turn_seq",
                (source_session_id, turn_seq),
            ).fetchall()
            if any(row["status"] == "running" for row in turns):
                raise ValueError("fork history contains a running turn")

            for turn in turns:
                self._fork_copy_turn(
                    source,
                    turn,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                    target_user_id=target_user_id,
                    target_channel=target_channel,
                    native_context=native_context,
                )

            for turn in turns:
                anchor = source.execute(
                    "SELECT payload_json FROM event_log WHERE "
                    "event_type = 'provider.turn_boundary' AND turn_id = ? "
                    "ORDER BY seq DESC LIMIT 1",
                    (turn["turn_id"],),
                ).fetchone()
                if anchor is not None:
                    self.record_provider_fact(
                        session_id=target_session_id,
                        kind="turn_boundary",
                        turn_id=str(turn["turn_id"]),
                        data=json.loads(anchor["payload_json"]),
                    )

            if boundary_event is not None:
                self._fork_copy_recall_events(
                    source,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                    through_event_seq=int(boundary_event["seq"]),
                    next_legacy_source_seq=next_legacy_source_seq,
                )

            self.rebuild_projections()
            return turn_seq
        finally:
            source.close()

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
                "FROM transcript_message_payloads WHERE session_id = ? "
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
            orphans = self._conn.execute(
                "SELECT session_id, turn_id FROM transcript_turns "
                "WHERE status = 'running' ORDER BY turn_seq",
            ).fetchall()
            if not orphans:
                return 0
            with self._transaction():
                timestamp = _utc_now()
                cursor = self._conn.execute(
                    "UPDATE transcript_turns SET status = 'cancelled', "
                    "finished_at = COALESCE(finished_at, ?) "
                    "WHERE status = 'running'",
                    (timestamp,),
                )
                for orphan in orphans:
                    turn_id = str(orphan["turn_id"])
                    self._append_fact(
                        event_type="turn.cancelled",
                        payload={
                            "error": None,
                            "finished_at": timestamp,
                            "status": "cancelled",
                        },
                        idempotency_key=f"turn:{turn_id}:terminal",
                        recorded_at=timestamp,
                        turn_id=turn_id,
                    )
                for orphan in orphans:
                    commit_turn_revision(
                        self._conn,
                        session_id=str(orphan["session_id"]),
                        turn_id=str(orphan["turn_id"]),
                    )
                return cursor.rowcount

    def rebuild_projections(self) -> None:
        """Recreate UI and runtime projections from append-only facts."""
        with self._transaction():
            rebuild_projections(self._conn)

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
                    storage_id=self._storage_id,
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
                    "session_id, storage_id, user_id, channel, "
                    "next_turn_seq) VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        self._storage_id,
                        user_id,
                        channel,
                        len(turns) + 1,
                    ),
                )
            self._append_session_fact(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                recorded_at=now,
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
                self._append_fact(
                    event_type="turn.started",
                    payload={
                        "created_at": created_at,
                        "replaces_turn_id": None,
                        "turn_seq": turn_seq,
                    },
                    idempotency_key=f"turn:{turn_id}:started",
                    recorded_at=created_at,
                    turn_id=turn_id,
                )
                for ordinal, message in enumerate(turn_messages):
                    metadata = message.metadata or {}
                    self._conn.execute(
                        "INSERT INTO transcript_messages("
                        "session_id, turn_id, message_id, ordinal, role, "
                        "envelope_json, created_at, client_message_id, "
                        "finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            turn_id,
                            message.id,
                            ordinal,
                            _enum_value(message.role),
                            message_envelope(message),
                            str(metadata.get("timestamp") or created_at),
                            self._client_message_id(message),
                            metadata.get("finished_at"),
                        ),
                    )
                    blocks = message.model_dump(mode="json")["content"]
                    write_message_blocks(
                        self._conn,
                        session_id=session_id,
                        message_id=message.id,
                        content=blocks,
                    )
                    envelope_ref = self._write_fact_object(
                        codec="message-envelope-v1",
                        value=json.loads(message_envelope(message)),
                    )
                    block_refs = []
                    for block in blocks:
                        content_ref = self._write_fact_object(
                            codec="message-block-v1",
                            value=block,
                        )
                        block_refs.append(content_ref)
                    snapshot_hash = hashlib.sha256(
                        _canonical_json(
                            {
                                "blocks": block_refs,
                                "envelope": envelope_ref,
                                "finished_at": metadata.get("finished_at"),
                                "ordinal": ordinal,
                            },
                        ).encode("utf-8"),
                    ).hexdigest()
                    self._append_fact(
                        event_type="message.committed",
                        payload={
                            "block_refs": block_refs,
                            "client_message_id": self._client_message_id(
                                message,
                            ),
                            "created_at": str(
                                metadata.get("timestamp") or created_at,
                            ),
                            "envelope_ref": envelope_ref,
                            "finished_at": metadata.get("finished_at"),
                            "ordinal": ordinal,
                            "role": _enum_value(message.role),
                        },
                        idempotency_key=(
                            f"message:{message.id}:{snapshot_hash}"
                        ),
                        recorded_at=created_at,
                        turn_id=turn_id,
                        message_id=message.id,
                    )
                self._append_fact(
                    event_type="turn.completed",
                    payload={
                        "error": None,
                        "finished_at": finished_at,
                        "status": "completed",
                    },
                    idempotency_key=f"turn:{turn_id}:terminal",
                    recorded_at=finished_at,
                    turn_id=turn_id,
                )
            self._append_fact(
                event_type="migration.json_imported",
                payload={"message_count": len(messages)},
                idempotency_key="migration:json",
                recorded_at=now,
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
                "session_id, storage_id, user_id, channel) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (
                    session_id,
                    self._storage_id,
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
                storage_id=self._storage_id,
            )
            self._append_session_fact(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                recorded_at=timestamp,
            )
            existing = self._conn.execute(
                "SELECT turn_seq, replaces_turn_id, created_at "
                "FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if existing is not None:
                if existing["replaces_turn_id"] != replaces_turn_id:
                    raise ValueError("transcript replacement target mismatch")
                original_timestamp = str(existing["created_at"])
                self._append_fact(
                    event_type="turn.started",
                    payload={
                        "created_at": original_timestamp,
                        "replaces_turn_id": replaces_turn_id,
                        "turn_seq": int(existing["turn_seq"]),
                    },
                    idempotency_key=f"turn:{turn_id}:started",
                    recorded_at=original_timestamp,
                    turn_id=turn_id,
                )
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
            self._append_fact(
                event_type="turn.started",
                payload={
                    "created_at": timestamp,
                    "replaces_turn_id": replaces_turn_id,
                    "turn_seq": turn_seq,
                },
                idempotency_key=f"turn:{turn_id}:started",
                recorded_at=timestamp,
                turn_id=turn_id,
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
        user_id: str | None = None,
        channel: str | None = None,
        turn_id: str,
        message: Message,
        ordinal: int,
        created_at: str | None = None,
        finished_at: str | None = None,
        force_event: bool = False,
    ) -> None:
        """Insert or update one complete display message snapshot."""
        del user_id, channel
        payload = message_envelope(message)
        role = _enum_value(message.role)
        client_message_id = self._client_message_id(message)
        timestamp = created_at or _utc_now()
        blocks = message.model_dump(mode="json")["content"]
        with self._transaction():
            turn = self._conn.execute(
                "SELECT 1 FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if turn is None:
                raise ValueError("transcript turn does not exist")
            existing = self._conn.execute(
                "SELECT turn_id, ordinal, role, envelope_json, "
                "client_message_id, created_at, finished_at "
                "FROM transcript_messages "
                "WHERE session_id = ? AND message_id = ?",
                (session_id, message.id),
            ).fetchone()
            if existing is not None and existing["turn_id"] != turn_id:
                raise ValueError("transcript message belongs to another turn")
            if existing is not None:
                timestamp = str(existing["created_at"])

            write_message_envelope(
                self._conn,
                session_id=session_id,
                turn_id=turn_id,
                message_id=message.id,
                ordinal=ordinal,
                role=role,
                envelope_json=payload,
                client_message_id=client_message_id,
                created_at=timestamp,
                finished_at=finished_at,
            )

            write_message_blocks(
                self._conn,
                session_id=session_id,
                message_id=message.id,
                content=blocks,
            )
            envelope_ref = self._write_fact_object(
                codec="message-envelope-v1",
                value=json.loads(payload),
            )
            block_refs = []
            for block in blocks:
                content_ref = self._write_fact_object(
                    codec="message-block-v1",
                    value=block,
                )
                block_refs.append(content_ref)
            snapshot_hash = hashlib.sha256(
                _canonical_json(
                    {
                        "blocks": block_refs,
                        "envelope": envelope_ref,
                        "finished_at": finished_at,
                        "ordinal": ordinal,
                    },
                ).encode("utf-8"),
            ).hexdigest()
            key_prefix = f"message:{message.id}:{snapshot_hash}"
            latest = self._conn.execute(
                "SELECT idempotency_key FROM event_log "
                "WHERE message_id = ? AND event_type = 'message.committed' "
                "ORDER BY seq DESC LIMIT 1",
                (message.id,),
            ).fetchone()
            if (
                not force_event
                and latest
                and (
                    latest[0] == key_prefix
                    or latest[0].startswith(key_prefix + ":")
                )
            ):
                return
            self._append_fact(
                event_type="message.committed",
                payload={
                    "block_refs": block_refs,
                    "client_message_id": client_message_id,
                    "created_at": timestamp,
                    "envelope_ref": envelope_ref,
                    "finished_at": finished_at,
                    "ordinal": ordinal,
                    "role": role,
                },
                idempotency_key=f"{key_prefix}:{uuid4().hex}",
                recorded_at=timestamp,
                turn_id=turn_id,
                message_id=message.id,
            )

    def read_replay_page(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        channel: str | None = None,
        turn_id: str,
        through: int,
        after: int,
    ) -> list[tuple[int, str]]:
        """Read committed envelope messages without exposing running turns.

        Envelope terminal message sequence numbers do not change when the
        containing response is finalized. Later completions are excluded.
        """
        del user_id, channel
        result: list[tuple[int, str]] = []
        size = 0
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT ordinal,payload_json FROM transcript_message_payloads "
                "WHERE session_id = ? AND turn_id = ? AND ordinal > ? "
                "AND json_extract(envelope_json, "
                "'$.sequence_number') <= ? "
                "AND role != 'user' ORDER BY ordinal LIMIT 40",
                (session_id, turn_id, after, through),
            )
            for row in rows:
                payload = str(row["payload_json"])
                length = len(payload.encode("utf-8"))
                if length > 8 * 1024 * 1024:
                    raise ValueError("replay message exceeds byte budget")
                if result and size + length > 2 * 1024 * 1024:
                    break
                result.append((int(row["ordinal"]), payload))
                size += length
        return result

    def commit_turn(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        channel: str | None = None,
        turn_id: str,
        status: TurnStatus,
        messages: list[tuple[Message, int]],
        runtime: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> None:
        """Commit final projections and their facts as one transaction."""
        del user_id, channel
        with self._transaction():
            session = self._session_row(session_id)
            if session is None:
                raise ValueError("transcript session does not exist")
            for message, ordinal in messages:
                self.upsert_message(
                    session_id=session_id,
                    turn_id=turn_id,
                    message=message,
                    ordinal=ordinal,
                    finished_at=finished_at,
                )
            if runtime is not None:
                self.write_runtime_state(
                    session_id=session_id,
                    user_id=session["user_id"],
                    channel=session["channel"],
                    turn_id=turn_id,
                    current_usage=usage,
                    **runtime,
                )
            elif (
                usage is not None
                and self._conn.execute(
                    "SELECT 1 FROM session_runtime WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                is not None
            ):
                self.set_current_usage(session_id=session_id, **usage)
            if usage is not None:
                self.attach_turn_usage(
                    session_id=session_id,
                    turn_id=turn_id,
                    **usage,
                )
            self.finish_turn(
                session_id=session_id,
                turn_id=turn_id,
                status=status,
                error=error,
                finished_at=finished_at,
            )

    def finish_turn(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        channel: str | None = None,
        turn_id: str,
        status: TurnStatus,
        error: dict[str, Any] | None = None,
        finished_at: str | None = None,
    ) -> None:
        """Set a terminal turn status and activate successful replacements."""
        del user_id, channel
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
            self._append_fact(
                event_type=f"turn.{status}",
                payload={
                    "error": error,
                    "finished_at": timestamp,
                    "status": status,
                },
                idempotency_key=f"turn:{turn_id}:terminal",
                recorded_at=timestamp,
                turn_id=turn_id,
            )
            commit_turn_revision(
                self._conn,
                session_id=session_id,
                turn_id=turn_id,
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
        user_id: str | None = None,
        channel: str | None = None,
        turn_id: str,
        usage: dict[str, Any] | None,
        context_usage: dict[str, Any] | None,
    ) -> bool:
        """Attach one usage snapshot to the turn's closing assistant."""
        del user_id, channel
        snapshot = {
            "usage": usage,
            "context_usage": context_usage,
        }
        with self._transaction():
            row = self._conn.execute(
                "SELECT message_id, envelope_json "
                "FROM transcript_messages "
                "WHERE session_id = ? AND turn_id = ? "
                "AND role = 'assistant' "
                "ORDER BY ordinal DESC LIMIT 1",
                (session_id, turn_id),
            ).fetchone()
            if row is None:
                return False

            message = Message.model_validate_json(row["envelope_json"])
            metadata = dict(message.metadata or {})
            if metadata.get(TURN_USAGE_META_KEY) == snapshot:
                return True

            metadata[TURN_USAGE_META_KEY] = snapshot
            updated = message.model_copy(
                update={"metadata": metadata},
                deep=True,
            )
            self._conn.execute(
                "UPDATE transcript_messages SET envelope_json = ? "
                "WHERE session_id = ? AND message_id = ?",
                (
                    message_envelope(updated),
                    session_id,
                    row["message_id"],
                ),
            )
            usage_json = _canonical_json(snapshot)
            usage_ref = self._write_fact_object(
                codec="turn-usage-v1",
                value=snapshot,
            )
            timestamp = _utc_now()
            event_seq = self._append_fact(
                event_type="turn.usage_attached",
                payload={"usage_ref": usage_ref},
                idempotency_key=f"turn:{turn_id}:usage:{usage_ref}",
                recorded_at=timestamp,
                turn_id=turn_id,
                message_id=str(row["message_id"]),
            )
            self._conn.execute(
                "INSERT INTO projection_turn_usage VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id, turn_id) DO UPDATE SET "
                "usage_json=excluded.usage_json, "
                "event_seq=excluded.event_seq",
                (session_id, turn_id, usage_json, event_seq),
            )
            return True

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
        after_message_id: str | None = None,
        before_message_id: str | None = None,
        limit: int = 5,
        max_bytes: int = _DEFAULT_PAGE_MAX_BYTES,
        max_content_blocks: int = _DEFAULT_PAGE_MAX_CONTENT_BLOCKS,
    ) -> TranscriptPage | None:
        """Read a turn-, block-, and byte-bounded durable history page."""
        if (
            sum(
                value is not None
                for value in (
                    before,
                    after_message_id,
                    before_message_id,
                )
            )
            > 1
        ):
            raise ValueError("history boundaries are mutually exclusive")
        if limit < 1 or limit > 100:
            raise ValueError(
                "transcript turn limit must be between 1 and 100",
            )
        if max_bytes < 1:
            raise ValueError("transcript page max_bytes must be positive")
        if max_content_blocks < 1:
            raise ValueError(
                "transcript page max_content_blocks must be positive",
            )
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            snapshot_turn_seq = (
                before.snapshot_turn_seq
                if before is not None and before.snapshot_turn_seq is not None
                else max(0, int(session["next_turn_seq"]) - 1)
            )
            snapshot_event_seq = (
                before.snapshot_event_seq
                if before is not None and before.snapshot_event_seq is not None
                else int(
                    connection.execute(
                        "SELECT COALESCE(MAX(seq), 0) FROM event_log",
                    ).fetchone()[0],
                )
            )
            if before_message_id is not None:
                boundary = connection.execute(
                    "SELECT t.turn_seq FROM transcript_messages m "
                    "JOIN transcript_turns t ON t.session_id=m.session_id "
                    "AND t.turn_id=m.turn_id WHERE m.session_id=? "
                    "AND m.message_id=? AND m.superseded_at IS NULL",
                    (session_id, before_message_id),
                ).fetchone()
                if boundary is None:
                    raise ValueError("history boundary message not found")
                before = TranscriptCursor(
                    turn_seq=int(boundary["turn_seq"]),
                    ordinal=0,
                    snapshot_turn_seq=snapshot_turn_seq,
                    snapshot_event_seq=snapshot_event_seq,
                )
            turn_sql = "SELECT t.turn_seq FROM transcript_turns t "
            after_turn_seq: int | None = None
            if after_message_id is not None:
                boundary = connection.execute(
                    "SELECT t.turn_seq FROM transcript_messages m "
                    "JOIN transcript_turns t ON t.session_id = m.session_id "
                    "AND t.turn_id = m.turn_id WHERE m.session_id = ? "
                    "AND m.message_id = ? AND m.superseded_at IS NULL",
                    (session_id, after_message_id),
                ).fetchone()
                if boundary is None:
                    raise ValueError("history boundary message not found")
                after_turn_seq = int(boundary["turn_seq"])
                following = connection.execute(
                    "SELECT t.turn_seq FROM transcript_turns t "
                    "WHERE t.session_id = ? AND t.turn_seq > ? "
                    "AND t.turn_seq <= ? AND EXISTS ("
                    "SELECT 1 FROM transcript_messages m "
                    "WHERE m.session_id = t.session_id "
                    "AND m.turn_id = t.turn_id "
                    "AND m.superseded_at IS NULL "
                    "AND (t.status != 'running' OR m.role = 'user')) "
                    "ORDER BY t.turn_seq ASC LIMIT ?",
                    (
                        session_id,
                        boundary["turn_seq"],
                        snapshot_turn_seq,
                        limit,
                    ),
                ).fetchall()
                if not following:
                    return TranscriptPage(
                        messages=[],
                        next_before=None,
                        has_more=False,
                        snapshot_turn_seq=snapshot_turn_seq,
                        snapshot_event_seq=snapshot_event_seq,
                    )
                before = TranscriptCursor(
                    turn_seq=int(following[-1]["turn_seq"]) + 1,
                    ordinal=0,
                    snapshot_turn_seq=snapshot_turn_seq,
                    snapshot_event_seq=snapshot_event_seq,
                )
            turn_sql += "WHERE t.session_id = ? AND t.turn_seq <= ? "
            params: list[Any] = [session_id, snapshot_turn_seq]
            if after_turn_seq is not None:
                turn_sql += "AND t.turn_seq > ? "
                params.append(after_turn_seq)
            if before is not None:
                at_turn_boundary = (
                    before.ordinal == 0 and before.content_before == 0
                )
                operator = "<" if at_turn_boundary else "<="
                turn_sql += f"AND t.turn_seq {operator} ? "
                params.append(before.turn_seq)
            turn_sql += (
                "AND EXISTS (SELECT 1 FROM transcript_messages vm "
                "WHERE vm.session_id = t.session_id "
                "AND vm.turn_id = t.turn_id "
                "AND (t.status != 'running' OR vm.role = 'user')) AND "
                + _VISIBLE_TURN_AT_SNAPSHOT
                + "ORDER BY t.turn_seq DESC LIMIT ?"
            )
            params.extend([snapshot_event_seq, limit + 1])
            candidates = connection.execute(turn_sql, params).fetchall()
            selected_turns = [
                int(row["turn_seq"]) for row in candidates[:limit]
            ]
            if not selected_turns:
                return TranscriptPage(
                    messages=[],
                    next_before=None,
                    has_more=False,
                    snapshot_turn_seq=snapshot_turn_seq,
                    snapshot_event_seq=snapshot_event_seq,
                )

            message_filter = (
                "FROM transcript_turns t CROSS JOIN transcript_messages m "
                "ON m.session_id = t.session_id AND m.turn_id = t.turn_id "
                "WHERE t.session_id = ? AND "
                + _VISIBLE_TURN_AT_SNAPSHOT
                + "AND (t.status != 'running' OR m.role = 'user') "
                "AND t.turn_seq IN (SELECT value FROM json_each(?)) "
            )
            message_params: list[Any] = [
                session_id,
                snapshot_event_seq,
                json.dumps(selected_turns),
            ]
            if before is not None and (
                before.ordinal > 0 or before.content_before > 0
            ):
                message_filter += "AND (t.turn_seq < ? OR "
                message_filter += (
                    "(t.turn_seq = ? AND m.ordinal <= ?)) "
                    if before.content_before > 0
                    else "(t.turn_seq = ? AND m.ordinal < ?)) "
                )
                message_params.extend(
                    [before.turn_seq, before.turn_seq, before.ordinal],
                )

            size_sql = (
                "SELECT m.envelope_json, m.session_id, m.message_id, "
                "(SELECT COUNT(*) FROM transcript_blocks b "
                "WHERE b.session_id = m.session_id "
                "AND b.message_id = m.message_id) AS content_total, "
                "m.created_at AS message_created_at, "
                "m.finished_at AS message_finished_at, m.ordinal, "
                "t.turn_id, t.turn_seq, t.status AS turn_status, "
                "t.error_json, t.finished_at AS turn_finished_at "
                + message_filter
                + "ORDER BY t.turn_seq DESC, m.ordinal DESC"
            )
            selection = TranscriptPageBuilder().select(
                connection.execute(size_sql, message_params),
                connection=connection,
                before=before,
                snapshot_turn_seq=snapshot_turn_seq,
                snapshot_event_seq=snapshot_event_seq,
                max_bytes=max_bytes,
                max_content_blocks=max_content_blocks,
                has_more=len(candidates) > limit,
            )
            if not selection.messages:
                return TranscriptPage(
                    messages=[],
                    next_before=None,
                    has_more=False,
                    snapshot_turn_seq=snapshot_turn_seq,
                    snapshot_event_seq=snapshot_event_seq,
                )

            selection.messages.reverse()
            return TranscriptPage(
                messages=selection.messages,
                next_before=(
                    selection.oldest_position if selection.has_more else None
                ),
                has_more=selection.has_more,
                snapshot_turn_seq=snapshot_turn_seq,
                snapshot_event_seq=snapshot_event_seq,
            )

    def get_user_message_text(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        message_id: str,
    ) -> str | None:
        """Read one complete user input without loading assistant messages."""
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            row = connection.execute(
                "SELECT payload_json FROM transcript_message_payloads "
                "WHERE session_id = ? AND message_id = ? "
                "AND role = 'user' AND superseded_at IS NULL",
                (session_id, message_id),
            ).fetchone()
            if row is None:
                return None
            message = Message.model_validate_json(row["payload_json"])
            return "\n".join(
                part.text
                for part in message.content
                if isinstance(part, TextContent) and part.text
            )

    def get_user_message_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
        limit: int = 200,
    ) -> TranscriptUserMessagePage | None:
        """Read lightweight user-message entries for history navigation."""
        if limit < 1 or limit > 1000:
            raise ValueError(
                "user-message index limit must be between 1 and 1000",
            )
        with self._read_connection() as connection:
            connection.execute("BEGIN")
            session = self._session_row(session_id, connection)
            if session is None:
                return None
            self._assert_identity(
                session,
                user_id=user_id,
                channel=channel,
                storage_id=self._storage_id,
            )
            snapshot_turn_seq = (
                before.snapshot_turn_seq
                if before is not None and before.snapshot_turn_seq is not None
                else max(0, int(session["next_turn_seq"]) - 1)
            )
            snapshot_event_seq = (
                before.snapshot_event_seq
                if before is not None and before.snapshot_event_seq is not None
                else int(
                    connection.execute(
                        "SELECT COALESCE(MAX(seq), 0) FROM event_log",
                    ).fetchone()[0],
                )
            )
            query = (
                "SELECT m.message_id, m.created_at, "
                "m.client_message_id, "
                "m.ordinal, t.turn_seq "
                "FROM transcript_turns AS t "
                "JOIN transcript_messages AS m "
                "ON m.session_id = t.session_id "
                "AND m.turn_id = t.turn_id "
                "WHERE t.session_id = ? AND t.turn_seq <= ? "
                "AND m.role = 'user' AND " + _VISIBLE_TURN_AT_SNAPSHOT
            )
            params: list[Any] = [
                session_id,
                snapshot_turn_seq,
                snapshot_event_seq,
            ]
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM transcript_turns AS t "
                    "JOIN transcript_messages AS m "
                    "ON m.session_id = t.session_id AND m.turn_id = t.turn_id "
                    "WHERE t.session_id = ? AND t.turn_seq <= ? "
                    "AND m.role = 'user' AND " + _VISIBLE_TURN_AT_SNAPSHOT,
                    params,
                ).fetchone()[0],
            )
            if before is not None:
                query += (
                    "AND (t.turn_seq < ? OR "
                    "(t.turn_seq = ? AND m.ordinal < ?)) "
                )
                params.extend(
                    [before.turn_seq, before.turn_seq, before.ordinal],
                )
            query += "ORDER BY t.turn_seq DESC, m.ordinal DESC LIMIT ?"
            params.append(limit + 1)
            rows = connection.execute(query, params).fetchall()
            has_more = len(rows) > limit
            selected = rows[:limit]
            items = []
            for row in selected:
                preview = self._user_message_preview(
                    connection,
                    session_id,
                    str(row["message_id"]),
                )
                items.append(
                    TranscriptUserMessage(
                        message_id=str(row["message_id"]),
                        client_message_id=row["client_message_id"],
                        preview=preview,
                        created_at=str(row["created_at"]),
                        anchor=TranscriptCursor(
                            turn_seq=int(row["turn_seq"]) + 1,
                            ordinal=0,
                            snapshot_turn_seq=snapshot_turn_seq,
                            snapshot_event_seq=snapshot_event_seq,
                        ),
                    ),
                )
            items.reverse()
            next_before = None
            if has_more and selected:
                oldest = selected[-1]
                next_before = TranscriptCursor(
                    turn_seq=int(oldest["turn_seq"]),
                    ordinal=int(oldest["ordinal"]),
                    snapshot_turn_seq=snapshot_turn_seq,
                    snapshot_event_seq=snapshot_event_seq,
                )
            return TranscriptUserMessagePage(
                items=items,
                next_before=next_before,
                has_more=has_more,
                snapshot_turn_seq=snapshot_turn_seq,
                snapshot_event_seq=snapshot_event_seq,
                total=total,
            )

    @staticmethod
    def _user_message_preview(
        connection: sqlite3.Connection,
        session_id: str,
        message_id: str,
        limit: int = 160,
    ) -> str:
        """Read text blocks incrementally without decoding attachments."""
        blocks = connection.execute(
            "SELECT ordinal FROM transcript_blocks WHERE session_id = ? "
            "AND message_id = ? AND kind = 'text' ORDER BY ordinal",
            (session_id, message_id),
        )
        preview: list[str] = []
        for (ordinal,) in blocks:
            whitespace = bool(preview)
            offset = 1
            while True:
                text = (
                    connection.execute(
                        "SELECT substr(json_extract(payload_json, '$.text'), "
                        "?, 1024) FROM transcript_blocks WHERE session_id = ? "
                        "AND message_id = ? AND ordinal = ?",
                        (offset, session_id, message_id, ordinal),
                    ).fetchone()[0]
                    or ""
                )
                for char in text:
                    if char.isspace():
                        whitespace = bool(preview)
                        continue
                    if whitespace:
                        preview.append(" ")
                        whitespace = False
                    if len(preview) < limit:
                        preview.append(char)
                    if len(preview) >= limit:
                        return "".join(preview)
                if len(text) < 1024:
                    break
                offset += len(text)
        return "".join(preview)

    def find_turn_for_message(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        channel: str | None = None,
        message_id: str | None = None,
        client_message_id: str | None = None,
    ) -> str | None:
        """Resolve a regeneration target to its transcript turn."""
        del user_id, channel
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
