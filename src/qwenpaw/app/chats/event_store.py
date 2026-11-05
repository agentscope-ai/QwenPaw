# -*- coding: utf-8 -*-
"""Append-only event and immutable-object store for one conversation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from .event_schema import initialize_database

_BUSY_TIMEOUT_MS = 5_000


class EventConflictError(RuntimeError):
    """An idempotency key was reused for different event content."""


@dataclass(frozen=True)
class EventDraft:
    """One logical event to append in a transaction."""

    event_type: str
    payload: Mapping[str, Any]
    idempotency_key: str
    payload_version: int = 1
    turn_id: str | None = None
    message_id: str | None = None
    block_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


@dataclass(frozen=True)
class EventRecord:
    """One durable event returned from the log."""

    seq: int
    event_id: str
    event_type: str
    payload: dict[str, Any]
    payload_version: int
    idempotency_key: str
    recorded_at: str
    turn_id: str | None = None
    message_id: str | None = None
    block_id: str | None = None


@dataclass(frozen=True)
class ContentDraft:
    """One immutable content object to insert with an event batch."""

    codec: str
    payload: bytes

    @classmethod
    def from_text(cls, *, codec: str, payload: str) -> "ContentDraft":
        """Build an object from UTF-8 text."""
        return cls(codec=codec, payload=payload.encode("utf-8"))

    @property
    def content_hash(self) -> str:
        """Return the hash covering both codec and payload."""
        digest = hashlib.sha256()
        digest.update(self.codec.encode("utf-8"))
        digest.update(b"\0")
        digest.update(self.payload)
        return digest.hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _event_hash(draft: EventDraft, payload_json: str) -> str:
    envelope = {
        "block_id": draft.block_id,
        "event_type": draft.event_type,
        "message_id": draft.message_id,
        "payload": json.loads(payload_json),
        "payload_version": draft.payload_version,
        "turn_id": draft.turn_id,
    }
    return hashlib.sha256(
        _canonical_json(envelope).encode("utf-8"),
    ).hexdigest()


class ConversationEventStore:
    """Own the writer connection for one fresh conversation database."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            timeout=_BUSY_TIMEOUT_MS / 1000,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        try:
            initialize_database(self._conn)
            self._conn.execute("PRAGMA journal_mode=WAL")
        except BaseException:
            self._conn.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        """Return the physical database path."""
        return self._path

    def close(self) -> None:
        """Close the writer connection."""
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def _insert_object(self, draft: ContentDraft) -> str:
        content_hash = draft.content_hash
        self._conn.execute(
            "INSERT OR IGNORE INTO content_objects("
            "content_hash, codec, payload, byte_length) VALUES (?, ?, ?, ?)",
            (
                content_hash,
                draft.codec,
                draft.payload,
                len(draft.payload),
            ),
        )
        row = self._conn.execute(
            "SELECT codec, payload FROM content_objects "
            "WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row is None or row["codec"] != draft.codec:
            raise EventConflictError("content hash collision")
        if bytes(row["payload"]) != draft.payload:
            raise EventConflictError("content hash collision")
        return content_hash

    def _insert_event(self, draft: EventDraft) -> EventRecord:
        if not draft.event_type or not draft.idempotency_key:
            raise ValueError("event type and idempotency key are required")
        if draft.payload_version < 1:
            raise ValueError("payload version must be positive")
        payload_json = _canonical_json(draft.payload)
        payload_hash = _event_hash(draft, payload_json)
        cursor = self._conn.execute(
            "INSERT INTO event_log("
            "event_id, event_type, payload_version, turn_id, message_id, "
            "block_id, payload_json, payload_hash, idempotency_key, "
            "recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(idempotency_key) DO NOTHING",
            (
                draft.event_id,
                draft.event_type,
                draft.payload_version,
                draft.turn_id,
                draft.message_id,
                draft.block_id,
                payload_json,
                payload_hash,
                draft.idempotency_key,
                draft.recorded_at,
            ),
        )
        if cursor.rowcount == 0:
            row = self._conn.execute(
                "SELECT * FROM event_log WHERE idempotency_key = ?",
                (draft.idempotency_key,),
            ).fetchone()
            if row is None or row["payload_hash"] != payload_hash:
                raise EventConflictError(
                    "idempotency key payload does not match",
                )
            return self._record(row)
        lastrowid = cursor.lastrowid
        if lastrowid is None:
            raise RuntimeError("appended event has no row identity")
        row = self._conn.execute(
            "SELECT * FROM event_log WHERE seq = ?",
            (int(lastrowid),),
        ).fetchone()
        if row is None:
            raise RuntimeError("appended event cannot be read back")
        return self._record(row)

    def append_batch(
        self,
        events: Iterable[EventDraft],
        *,
        objects: Iterable[ContentDraft] = (),
    ) -> list[EventRecord]:
        """Atomically insert immutable objects and append logical events."""
        event_list = list(events)
        object_list = list(objects)
        if not event_list and not object_list:
            return []
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for draft in object_list:
                    self._insert_object(draft)
                records = [self._insert_event(draft) for draft in event_list]
            except BaseException:
                self._conn.rollback()
                raise
            self._conn.commit()
            return records

    def append(self, event: EventDraft) -> EventRecord:
        """Append one event and return its durable identity."""
        return self.append_batch([event])[0]

    @staticmethod
    def _record(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            seq=int(row["seq"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            payload=json.loads(row["payload_json"]),
            payload_version=int(row["payload_version"]),
            idempotency_key=str(row["idempotency_key"]),
            recorded_at=str(row["recorded_at"]),
            turn_id=row["turn_id"],
            message_id=row["message_id"],
            block_id=row["block_id"],
        )

    def iter_events(self, *, after_seq: int = 0) -> Iterator[EventRecord]:
        """Read committed events in append order using a read-only handle."""
        if after_seq < 0:
            raise ValueError("after_seq must not be negative")
        uri = f"{self._path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT * FROM event_log WHERE seq > ? ORDER BY seq",
                (after_seq,),
            ).fetchall()
        finally:
            connection.close()
        return iter(self._record(row) for row in rows)

    def read_object(self, content_hash: str) -> tuple[str, bytes] | None:
        """Read one immutable object by hash."""
        uri = f"{self._path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT codec, payload FROM content_objects "
                "WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return str(row["codec"]), bytes(row["payload"])


__all__ = [
    "ContentDraft",
    "ConversationEventStore",
    "EventConflictError",
    "EventDraft",
    "EventRecord",
]
