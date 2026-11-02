# -*- coding: utf-8 -*-
"""Rebuild mutable conversation projections from immutable session facts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ...schemas import Message
from ...token_usage.turn_usage import TURN_USAGE_META_KEY
from .context_revisions import read_revision_state
from .transcript_blocks import (
    message_envelope,
    write_message_blocks,
    write_message_envelope,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _object_json(connection: sqlite3.Connection, content_hash: str) -> Any:
    row = connection.execute(
        "SELECT payload FROM content_objects WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if row is None:
        raise ValueError("event content object is missing")
    return json.loads(bytes(row[0]).decode("utf-8"))


def _events(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM event_log ORDER BY seq",
    ).fetchall()


def _session_identity(
    rows: list[sqlite3.Row],
) -> tuple[str, str, str, str]:
    for row in rows:
        if row["event_type"] != "session.created":
            continue
        payload = json.loads(row["payload_json"])
        return (
            str(payload["session_id"]),
            str(payload["storage_id"]),
            str(payload["user_id"]),
            str(payload["channel"]),
        )
    raise ValueError("session identity event is missing")


def _project_message(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    row: sqlite3.Row,
    payload: dict[str, Any],
) -> None:
    message_id = str(row["message_id"])
    turn_id = str(row["turn_id"])
    envelope = _object_json(connection, str(payload["envelope_ref"]))
    envelope_json = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    write_message_envelope(
        connection,
        session_id=session_id,
        turn_id=turn_id,
        message_id=message_id,
        ordinal=int(payload["ordinal"]),
        role=str(payload["role"]),
        envelope_json=envelope_json,
        client_message_id=payload.get("client_message_id"),
        created_at=str(payload["created_at"]),
        finished_at=payload.get("finished_at"),
    )
    write_message_blocks(
        connection,
        session_id=session_id,
        message_id=message_id,
        content=[
            _object_json(connection, str(ref)) for ref in payload["block_refs"]
        ],
    )


def _project_terminal(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    row: sqlite3.Row,
    payload: dict[str, Any],
) -> None:
    turn_id = str(row["turn_id"])
    error = payload.get("error")
    error_json = (
        json.dumps(error, ensure_ascii=False, sort_keys=True)
        if error is not None
        else None
    )
    connection.execute(
        "UPDATE transcript_turns SET status = ?, error_json = ?, "
        "finished_at = ? WHERE session_id = ? AND turn_id = ?",
        (
            str(payload["status"]),
            error_json,
            str(payload["finished_at"]),
            session_id,
            turn_id,
        ),
    )
    revision = connection.execute(
        "SELECT revision_id FROM context_revisions "
        "WHERE session_id = ? AND anchor_turn_id = ? "
        "ORDER BY rowid DESC LIMIT 1",
        (session_id, turn_id),
    ).fetchone()
    if revision is not None:
        connection.execute(
            "INSERT OR REPLACE INTO turn_context_revision VALUES (?, ?, ?)",
            (session_id, turn_id, revision[0]),
        )
    if payload["status"] != "completed":
        return
    replaced = connection.execute(
        "SELECT replaces_turn_id FROM transcript_turns "
        "WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone()
    if replaced is not None and replaced[0] is not None:
        connection.execute(
            "UPDATE transcript_messages SET superseded_at = ? "
            "WHERE session_id = ? AND turn_id = ?",
            (payload["finished_at"], session_id, replaced[0]),
        )


def _project_usage(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    row: sqlite3.Row,
    payload: dict[str, Any],
) -> None:
    usage = _object_json(connection, str(payload["usage_ref"]))
    message = connection.execute(
        "SELECT envelope_json FROM transcript_messages "
        "WHERE session_id = ? AND message_id = ?",
        (session_id, row["message_id"]),
    ).fetchone()
    if message is None:
        return
    model = Message.model_validate_json(message[0])
    metadata = dict(model.metadata or {})
    metadata[TURN_USAGE_META_KEY] = usage
    updated = model.model_copy(update={"metadata": metadata}, deep=True)
    connection.execute(
        "UPDATE transcript_messages SET envelope_json = ? "
        "WHERE session_id = ? AND message_id = ?",
        (message_envelope(updated), session_id, row["message_id"]),
    )
    connection.execute(
        "INSERT INTO projection_turn_usage VALUES (?, ?, ?, ?) "
        "ON CONFLICT(session_id, turn_id) DO UPDATE SET "
        "usage_json=excluded.usage_json, event_seq=excluded.event_seq",
        (
            session_id,
            row["turn_id"],
            _canonical_json(usage),
            int(row["seq"]),
        ),
    )


def _project_conversation_event(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    row: sqlite3.Row,
    payload: dict[str, Any],
) -> tuple[int | None, dict[str, Any] | None]:
    """Apply one UI/runtime event and return changed head metadata."""
    event_type = str(row["event_type"])
    if event_type == "turn.started":
        turn_seq = int(payload["turn_seq"])
        connection.execute(
            "INSERT INTO transcript_turns("
            "session_id, turn_seq, turn_id, status, "
            "replaces_turn_id, created_at) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (
                session_id,
                turn_seq,
                row["turn_id"],
                payload.get("replaces_turn_id"),
                payload["created_at"],
            ),
        )
        return turn_seq, None
    if event_type == "message.committed":
        _project_message(
            connection,
            session_id=session_id,
            row=row,
            payload=payload,
        )
    elif event_type in {
        "turn.completed",
        "turn.failed",
        "turn.cancelled",
    }:
        _project_terminal(
            connection,
            session_id=session_id,
            row=row,
            payload=payload,
        )
    elif event_type == "turn.excluded":
        connection.execute(
            "DELETE FROM transcript_turns WHERE session_id = ? "
            "AND turn_id = ?",
            (session_id, row["turn_id"]),
        )
    elif event_type == "turn.usage_attached":
        _project_usage(
            connection,
            session_id=session_id,
            row=row,
            payload=payload,
        )
    elif event_type == "runtime.committed":
        return None, payload
    return None, None


def rebuild_projections(connection: sqlite3.Connection) -> None:
    """Recreate UI and runtime heads without changing immutable facts."""
    rows = _events(connection)
    session_id, storage_id, user_id, channel = _session_identity(rows)
    connection.execute("DELETE FROM transcript_blocks")
    connection.execute("DELETE FROM transcript_messages")
    connection.execute("DELETE FROM projection_turn_usage")
    connection.execute("DELETE FROM turn_context_revision")
    connection.execute("DELETE FROM transcript_turns")
    connection.execute("DELETE FROM session_runtime")
    connection.execute(
        "UPDATE transcript_sessions SET next_turn_seq = 1 "
        "WHERE session_id = ?",
        (session_id,),
    )
    latest_runtime: dict[str, Any] | None = None
    recall_rows: dict[int, dict[str, Any]] = {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        event_type = str(row["event_type"])
        if event_type == "recall.entry_committed":
            recall_rows[int(payload["source_seq"])] = _object_json(
                connection,
                str(payload["entry_ref"]),
            )
        elif event_type == "recall.entries_purged":
            purge = _object_json(connection, str(payload["purge_ref"]))
            for seq in purge["seqs"]:
                recall_rows.pop(int(seq), None)
        else:
            _, runtime = _project_conversation_event(
                connection,
                session_id=session_id,
                row=row,
                payload=payload,
            )
            if runtime is not None:
                latest_runtime = runtime
    max_turn_seq = connection.execute(
        "SELECT COALESCE(MAX(turn_seq), 0) FROM transcript_turns "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    connection.execute(
        "UPDATE transcript_sessions SET storage_id = ?, user_id = ?, "
        "channel = ?, next_turn_seq = ? WHERE session_id = ?",
        (storage_id, user_id, channel, max_turn_seq + 1, session_id),
    )
    if latest_runtime is not None:
        revision_id = str(latest_runtime["revision_id"])
        revision = connection.execute(
            "SELECT context_generation, current_usage_json, created_at "
            "FROM context_revisions WHERE session_id = ? "
            "AND revision_id = ?",
            (session_id, revision_id),
        ).fetchone()
        if revision is None:
            raise ValueError("runtime revision is missing")
        state = read_revision_state(
            connection,
            session_id=session_id,
            revision_id=revision_id,
        )
        connection.execute(
            "INSERT INTO session_runtime VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                int(revision["context_generation"]),
                _canonical_json(state),
                revision["current_usage_json"],
                revision["created_at"],
            ),
        )
    recall_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'conversation_history'",
    ).fetchone()
    if recall_table is not None:
        connection.execute("DELETE FROM conversation_history")
        columns = (
            "session_id",
            "agent_id",
            "kind",
            "role",
            "name",
            "content",
            "tool_call_id",
            "tool_input",
            "tool_state",
            "headline",
            "blocks",
            "metadata",
            "created_at",
            "dedup_key",
        )
        for seq, value in sorted(recall_rows.items()):
            connection.execute(
                "INSERT INTO conversation_history("
                "seq, "
                + ", ".join(columns)
                + ") VALUES ("
                + ", ".join("?" for _ in range(len(columns) + 1))
                + ")",
                (seq, *(value.get(column) for column in columns)),
            )
        fts = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'conversation_history_fts'",
        ).fetchone()
        if fts is not None:
            connection.execute(
                "INSERT INTO conversation_history_fts"
                "(conversation_history_fts) VALUES('rebuild')",
            )
    timestamp = datetime.now(timezone.utc).isoformat()
    last_seq = int(rows[-1]["seq"]) if rows else 0
    connection.execute(
        "INSERT INTO projection_watermarks VALUES ('conversation', 1, ?, ?) "
        "ON CONFLICT(projector_name) DO UPDATE SET "
        "last_event_seq=excluded.last_event_seq, "
        "updated_at=excluded.updated_at",
        (last_seq, timestamp),
    )


__all__ = ["rebuild_projections"]
