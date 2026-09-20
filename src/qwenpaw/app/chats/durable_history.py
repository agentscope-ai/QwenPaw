# -*- coding: utf-8 -*-
"""Read user-visible chat history from Scroll's durable SQLite store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agentscope.message import Msg


_HISTORY_COLUMNS = (
    "seq, kind, role, name, content, tool_call_id, tool_state, "
    "blocks, metadata, created_at, dedup_key"
)


def _decode_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _tool_result_block(row: sqlite3.Row) -> dict[str, Any]:
    blocks = _decode_json(row["blocks"], [])
    if isinstance(blocks, list) and blocks:
        block = blocks[0]
        if isinstance(block, dict):
            return block
    return {
        "type": "tool_result",
        "id": row["tool_call_id"],
        "name": row["name"],
        "output": row["content"] or "",
        "state": row["tool_state"],
    }


def _insert_tool_result(msg: Msg, block: dict[str, Any]) -> bool:
    call_id = block.get("id")
    if not call_id:
        return False
    validated = Msg(
        name=msg.name,
        role=msg.role,
        content=[block],
    ).content[0]
    for index, candidate in enumerate(msg.content):
        candidate_id = getattr(candidate, "id", None)
        candidate_type = getattr(candidate, "type", None)
        if candidate_type == "tool_call" and candidate_id == call_id:
            msg.content.insert(index + 1, validated)
            return True
    return False


def _message_from_row(row: sqlite3.Row) -> Msg:
    blocks = _decode_json(row["blocks"], [])
    if not isinstance(blocks, list):
        raise ValueError("history blocks must be a list")
    if not blocks and row["content"] is not None:
        blocks = [{"type": "text", "text": row["content"]}]
    metadata = _decode_json(row["metadata"], {})
    if not isinstance(metadata, dict):
        raise ValueError("history metadata must be an object")
    role = row["role"] or "assistant"
    kwargs: dict[str, Any] = {
        "id": row["dedup_key"] or f"history-{row['seq']}",
        "name": row["name"] or role,
        "role": role,
        "content": blocks,
        "metadata": metadata,
    }
    if row["created_at"] is not None:
        kwargs["created_at"] = row["created_at"]
    return Msg(**kwargs)


def read_durable_session(db_path: Path, session_id: str) -> list[Msg]:
    """Return one session from an existing history database.

    The connection is strictly read-only: a missing or damaged database must
    never be created, quarantined, or otherwise changed by a GET endpoint.
    """
    if not db_path.is_file():
        return []

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT {_HISTORY_COLUMNS} FROM conversation_history "
            "WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()

    messages: list[Msg] = []
    current: Msg | None = None
    for row in rows:
        if row["kind"] != "tool_result":
            current = _message_from_row(row)
            messages.append(current)
            continue

        block = _tool_result_block(row)
        if current is not None and _insert_tool_result(current, block):
            continue
        kwargs: dict[str, Any] = {
            "id": row["dedup_key"] or f"history-{row['seq']}",
            "name": row["name"] or "assistant",
            "role": "assistant",
            "content": [block],
            "metadata": _decode_json(row["metadata"], {}),
        }
        if row["created_at"] is not None:
            kwargs["created_at"] = row["created_at"]
        current = Msg(**kwargs)
        messages.append(current)

    return messages
