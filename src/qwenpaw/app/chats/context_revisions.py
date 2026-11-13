# -*- coding: utf-8 -*-
"""Content-addressed runtime revisions for one conversation database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from typing import Any, Literal
from uuid import uuid4

_CONTEXT_KEY = "agent.state.context"
RevisionKind = Literal[
    "turn_commit",
    "snapshot",
    "usage_update",
    "state_update",
    "clear",
    "restore",
    "migration_anchor",
    "migration_approximate",
]


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_object(
    connection: sqlite3.Connection,
    *,
    value: Any,
    codec: str = "json-v1",
) -> str:
    payload = _canonical(value)
    content_hash = _digest(f"{codec}\0{payload}")
    encoded = payload.encode("utf-8")
    connection.execute(
        "INSERT OR IGNORE INTO content_objects("
        "content_hash, codec, payload, byte_length) VALUES (?, ?, ?, ?)",
        (
            content_hash,
            codec,
            encoded,
            len(encoded),
        ),
    )
    return content_hash


def _split_state(
    state: dict[str, Any],
) -> tuple[dict[str, Any], list[Any] | None]:
    components = deepcopy(state)
    agent = components.get("agent")
    if not isinstance(agent, dict):
        return components, None
    agent_state = agent.get("state")
    if not isinstance(agent_state, dict):
        return components, None
    context = agent_state.get("context")
    if not isinstance(context, list):
        return components, None
    agent_state.pop("context")
    return components, context


def _write_context(
    connection: sqlite3.Connection,
    context: list[Any],
) -> str:
    parent_hash: str | None = None
    for length, item in enumerate(context, start=1):
        item_hash = _write_object(
            connection,
            value=item,
            codec="context-item-v1",
        )
        node_payload = _canonical(
            {
                "item": item_hash,
                "length": length,
                "parent": parent_hash,
            },
        )
        node_hash = _digest(f"context-node-v1\0{node_payload}")
        connection.execute(
            "INSERT OR IGNORE INTO context_nodes("
            "node_hash, parent_node_hash, item_hash, length) "
            "VALUES (?, ?, ?, ?)",
            (node_hash, parent_hash, item_hash, length),
        )
        parent_hash = node_hash
    return _write_object(
        connection,
        value={"head": parent_hash, "length": len(context)},
        codec="context-ref-v1",
    )


def _write_components(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    revision_id: str,
    state: dict[str, Any],
) -> None:
    components, context = _split_state(state)
    if not state:
        content_hash = _write_object(
            connection,
            value={},
            codec="empty-state-v1",
        )
        connection.execute(
            "INSERT INTO revision_components VALUES (?, ?, ?, ?)",
            (session_id, revision_id, "", content_hash),
        )
    for key in sorted(components):
        content_hash = _write_object(connection, value=components[key])
        connection.execute(
            "INSERT INTO revision_components VALUES (?, ?, ?, ?)",
            (session_id, revision_id, key, content_hash),
        )
    if context is not None:
        content_hash = _write_context(connection, context)
        connection.execute(
            "INSERT INTO revision_components VALUES (?, ?, ?, ?)",
            (session_id, revision_id, _CONTEXT_KEY, content_hash),
        )


def record_revision(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str | None,
    state: dict[str, Any],
    generation: int,
    usage_json: str | None,
    created_at: str,
    kind: RevisionKind,
) -> str:
    """Append one immutable runtime revision in the transaction."""
    migration_anchor = kind in {"migration_anchor", "migration_approximate"}
    if turn_id is not None:
        turn = connection.execute(
            "SELECT status FROM transcript_turns "
            "WHERE session_id = ? AND turn_id = ?",
            (session_id, turn_id),
        ).fetchone()
        terminal = {"completed", "failed", "cancelled"}
        if turn is None or (
            turn[0] != "running"
            and not (migration_anchor and turn[0] in terminal)
        ):
            message = (
                "migration anchor requires a terminal turn"
                if migration_anchor
                else "context revision requires a running turn"
            )
            raise ValueError(message)

    parent = connection.execute(
        "SELECT revision_id FROM current_context_revision "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    revision_id = uuid4().hex
    connection.execute(
        "INSERT INTO context_revisions("
        "session_id, revision_id, parent_revision_id, anchor_turn_id, "
        "kind, context_generation, current_usage_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            revision_id,
            parent[0] if parent else None,
            turn_id,
            kind,
            generation,
            usage_json,
            created_at,
        ),
    )

    if kind == "usage_update" and parent is not None:
        # Usage writes leave state_json unchanged. All state writers update
        # the current revision in the same transaction as session_runtime.
        connection.execute(
            "INSERT INTO revision_components "
            "SELECT session_id, ?, component_key, content_hash "
            "FROM revision_components "
            "WHERE session_id = ? AND revision_id = ?",
            (revision_id, session_id, parent[0]),
        )
    else:
        _write_components(
            connection,
            session_id=session_id,
            revision_id=revision_id,
            state=state,
        )
    connection.execute(
        "INSERT INTO current_context_revision VALUES (?, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET "
        "revision_id = excluded.revision_id",
        (session_id, revision_id),
    )
    if migration_anchor and turn_id is not None:
        connection.execute(
            "INSERT OR REPLACE INTO turn_context_revision VALUES (?, ?, ?)",
            (session_id, turn_id, revision_id),
        )
    return revision_id


def commit_turn_revision(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
) -> None:
    """Bind the latest revision saved explicitly for this turn."""
    connection.execute(
        "INSERT OR IGNORE INTO turn_context_revision "
        "SELECT r.session_id, r.anchor_turn_id, r.revision_id "
        "FROM context_revisions r "
        "WHERE r.session_id = ? AND r.anchor_turn_id = ? "
        "ORDER BY r.rowid DESC LIMIT 1",
        (session_id, turn_id),
    )


def _read_object(
    connection: sqlite3.Connection,
    content_hash: str,
) -> tuple[str, Any]:
    row = connection.execute(
        "SELECT codec, payload FROM content_objects WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if row is None:
        raise ValueError("revision object is missing")
    return str(row[0]), json.loads(bytes(row[1]).decode("utf-8"))


def _read_context(
    connection: sqlite3.Connection,
    descriptor: dict[str, Any],
) -> list[Any]:
    expected = int(descriptor.get("length", 0))
    node_hash = descriptor.get("head")
    items: list[Any] = []
    while node_hash is not None:
        row = connection.execute(
            "SELECT parent_node_hash, item_hash FROM context_nodes "
            "WHERE node_hash = ?",
            (node_hash,),
        ).fetchone()
        if row is None:
            raise ValueError("context node is missing")
        _codec, item = _read_object(connection, str(row[1]))
        items.append(item)
        node_hash = row[0]
    items.reverse()
    if len(items) != expected:
        raise ValueError("context chain length mismatch")
    return items


def read_revision_state(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    revision_id: str,
) -> dict[str, Any]:
    """Rebuild one state dictionary from content-addressed components."""
    rows = connection.execute(
        "SELECT component_key, content_hash FROM revision_components "
        "WHERE session_id = ? AND revision_id = ? ORDER BY component_key",
        (session_id, revision_id),
    ).fetchall()
    if not rows:
        raise ValueError("revision components are missing")
    state: dict[str, Any] = {}
    context: list[Any] | None = None
    for row in rows:
        key = str(row[0])
        codec, value = _read_object(connection, str(row[1]))
        if codec == "empty-state-v1":
            if key != "" or value != {} or len(rows) != 1:
                raise ValueError("empty state descriptor is invalid")
            continue
        if key == _CONTEXT_KEY:
            if codec != "context-ref-v1" or not isinstance(value, dict):
                raise ValueError("context descriptor is invalid")
            context = _read_context(connection, value)
        else:
            state[key] = value
    if context is not None:
        agent = state.setdefault("agent", {})
        if not isinstance(agent, dict):
            raise ValueError("agent component is invalid")
        agent_state = agent.setdefault("state", {})
        if not isinstance(agent_state, dict):
            raise ValueError("agent state component is invalid")
        agent_state["context"] = context
    return state
