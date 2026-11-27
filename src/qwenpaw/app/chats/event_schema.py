# -*- coding: utf-8 -*-
"""Fresh append-only schema for one conversation database."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

APPLICATION_ID = 0x51504345
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE event_log (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT NOT NULL UNIQUE,
    event_type       TEXT NOT NULL,
    payload_version  INTEGER NOT NULL CHECK(payload_version > 0),
    turn_id          TEXT,
    message_id       TEXT,
    block_id         TEXT,
    payload_json     TEXT NOT NULL CHECK(json_valid(payload_json)),
    payload_hash     TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    recorded_at      TEXT NOT NULL
);

CREATE INDEX event_log_turn ON event_log(turn_id, seq);
CREATE INDEX event_log_message ON event_log(message_id, seq);
CREATE INDEX event_log_type ON event_log(event_type, seq);

CREATE TABLE content_objects (
    content_hash  TEXT PRIMARY KEY,
    codec         TEXT NOT NULL,
    payload       BLOB NOT NULL,
    byte_length   INTEGER NOT NULL CHECK(byte_length >= 0)
);

CREATE TABLE projection_watermarks (
    projector_name     TEXT PRIMARY KEY,
    projector_version  INTEGER NOT NULL CHECK(projector_version > 0),
    last_event_seq     INTEGER NOT NULL CHECK(last_event_seq >= 0),
    updated_at         TEXT NOT NULL
);

"""

_REQUIRED_TABLES = {
    "event_log",
    "content_objects",
    "projection_watermarks",
}


def advance_projection_watermark(
    connection: sqlite3.Connection,
    event_seq: int,
    *,
    updated_at: str | None = None,
) -> None:
    """Advance the inline conversation projector in the current transaction."""
    timestamp = updated_at or datetime.now(timezone.utc).isoformat()
    connection.execute(
        "INSERT INTO projection_watermarks VALUES "
        "('conversation', 1, ?, ?) "
        "ON CONFLICT(projector_name) DO UPDATE SET "
        "projector_version = excluded.projector_version, "
        "last_event_seq = MAX(last_event_seq, excluded.last_event_seq), "
        "updated_at = CASE WHEN excluded.last_event_seq >= last_event_seq "
        "THEN excluded.updated_at ELSE updated_at END",
        (event_seq, timestamp),
    )


def _user_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'",
    ).fetchall()
    return {str(row[0]) for row in rows}


def validate_database(connection: sqlite3.Connection) -> None:
    """Reject every database that is not the fresh event-store format."""
    application_id = int(
        connection.execute("PRAGMA application_id").fetchone()[0],
    )
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != APPLICATION_ID or version != SCHEMA_VERSION:
        raise ValueError("unsupported conversation event database")
    if not _REQUIRED_TABLES.issubset(_user_tables(connection)):
        raise ValueError("incomplete conversation event database")
    connection.execute(
        "SELECT seq, event_id, event_type, payload_version, payload_json, "
        "payload_hash, idempotency_key FROM event_log LIMIT 0",
    )
    connection.execute(
        "SELECT content_hash, codec, payload, byte_length "
        "FROM content_objects LIMIT 0",
    )


def initialize_database(connection: sqlite3.Connection) -> None:
    """Initialize only an empty database; never upgrade an old schema."""
    tables = _user_tables(connection)
    if not tables:
        with connection:
            connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    validate_database(connection)


__all__ = [
    "APPLICATION_ID",
    "SCHEMA_VERSION",
    "advance_projection_watermark",
    "initialize_database",
    "validate_database",
]
