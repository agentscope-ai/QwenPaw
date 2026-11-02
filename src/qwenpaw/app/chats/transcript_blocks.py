# -*- coding: utf-8 -*-
"""Shared message projection writes and envelope serialization."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from ...schemas import Message


def message_envelope(message: Message) -> str:
    """Serialize message metadata without duplicating block bodies."""
    return json.dumps(
        message.model_dump(mode="json", exclude={"content"}),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def write_message_envelope(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    ordinal: int,
    role: str,
    envelope_json: str,
    client_message_id: str | None,
    created_at: str,
    finished_at: str | None,
) -> None:
    """Materialize resolved message fields without appending any facts."""
    connection.execute(
        "INSERT INTO transcript_messages("
        "session_id, turn_id, message_id, ordinal, role, envelope_json, "
        "client_message_id, created_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(session_id, message_id) DO UPDATE SET "
        "turn_id=excluded.turn_id, ordinal=excluded.ordinal, "
        "role=excluded.role, envelope_json=excluded.envelope_json, "
        "client_message_id=excluded.client_message_id, "
        "created_at=excluded.created_at, finished_at=excluded.finished_at "
        "WHERE transcript_messages.envelope_json "
        "IS NOT excluded.envelope_json "
        "OR transcript_messages.ordinal != excluded.ordinal "
        "OR transcript_messages.created_at IS NOT excluded.created_at "
        "OR transcript_messages.finished_at IS NOT excluded.finished_at "
        "OR transcript_messages.client_message_id "
        "IS NOT excluded.client_message_id",
        (
            session_id,
            turn_id,
            message_id,
            ordinal,
            role,
            envelope_json,
            client_message_id,
            created_at,
            finished_at,
        ),
    )


def block_identity(session_id: str, message_id: str, ordinal: int) -> str:
    """Use session-scoped identity, independent of database row numbers."""
    key = json.dumps([session_id, message_id, ordinal], ensure_ascii=False)
    return uuid5(NAMESPACE_URL, f"qwenpaw:content:{key}").hex


def write_message_blocks(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    message_id: str,
    content: list[dict],
) -> None:
    """Replace materialized content within the message write transaction."""
    for ordinal, block in enumerate(content):
        payload = json.dumps(
            block,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        encoded = payload.encode("utf-8")
        connection.execute(
            "INSERT INTO transcript_blocks VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(session_id, message_id, ordinal) DO UPDATE SET "
            "kind = excluded.kind, content_hash = excluded.content_hash, "
            "payload_json = excluded.payload_json, "
            "byte_length = excluded.byte_length, version = "
            "transcript_blocks.version + 1 "
            "WHERE transcript_blocks.content_hash != excluded.content_hash",
            (
                session_id,
                message_id,
                block_identity(session_id, message_id, ordinal),
                ordinal,
                str(block.get("type") or "unknown"),
                hashlib.sha256(encoded).hexdigest(),
                payload,
                len(encoded),
            ),
        )
    connection.execute(
        "DELETE FROM transcript_blocks WHERE session_id = ? "
        "AND message_id = ? AND ordinal >= ?",
        (session_id, message_id, len(content)),
    )


def copy_message_blocks(
    connection: sqlite3.Connection,
    *,
    source_session_id: str,
    target_session_id: str,
) -> None:
    """Copy only blocks whose envelopes were selected into the new session."""
    rows = connection.execute(
        "SELECT b.* FROM parent.transcript_blocks b "
        "JOIN transcript_messages m ON m.message_id = b.message_id "
        "WHERE b.session_id = ? AND m.session_id = ?",
        (source_session_id, target_session_id),
    )
    for row in rows:
        connection.execute(
            "INSERT INTO transcript_blocks VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                target_session_id,
                row["message_id"],
                block_identity(
                    target_session_id,
                    row["message_id"],
                    row["ordinal"],
                ),
                row["ordinal"],
                row["kind"],
                row["content_hash"],
                row["payload_json"],
                row["byte_length"],
                row["version"],
            ),
        )
