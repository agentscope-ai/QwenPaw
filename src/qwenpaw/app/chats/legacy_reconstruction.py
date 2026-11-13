# -*- coding: utf-8 -*-
"""Rebuild approximate turn states from former Scroll history."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

from agentscope.message import Msg

from ...schemas import Message
from .utils import agentscope_msg_to_message


def _rows(path: Path, session_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'conversation_history'",
        ).fetchone()
        if exists is None:
            return []
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM conversation_history "
                "WHERE session_id = ? ORDER BY seq",
                (session_id,),
            )
        ]
    finally:
        connection.close()


def _message_rows(
    rows: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    agent = state.get("agent") or {}
    context = (agent.get("state") or {}).get("context") or []
    exact = {
        item.get("id"): item
        for item in context
        if isinstance(item, dict)
    }
    assistant_name = next(
        (item.get("name") for item in context
         if isinstance(item, dict) and item.get("role") == "assistant"),
        "assistant",
    )
    messages: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in rows:
        if row["kind"] not in {"context_msg", "model_turn"}:
            continue
        message_id = row["dedup_key"]
        if not message_id or not row["blocks"]:
            continue
        raw = exact.get(message_id)
        if raw is None:
            role = row["role"] or "assistant"
            raw = {
                "id": message_id,
                "name": "user" if role == "user" else assistant_name,
                "role": role,
                "content": json.loads(row["blocks"]),
                "metadata": json.loads(row["metadata"] or "{}"),
                "created_at": row["created_at"],
            }
        messages.append((deepcopy(raw), row))

    for row in rows:
        if row["kind"] != "tool_result" or not row["blocks"]:
            continue
        call_id = row["tool_call_id"]
        for raw, primary in reversed(messages):
            if primary["role"] != "assistant":
                continue
            blocks = raw.get("content") or []
            if not any(
                block.get("type") == "tool_call"
                and block.get("id") == call_id
                for block in blocks
            ):
                continue
            if not any(
                block.get("type") == "tool_result"
                and block.get("id") == call_id
                for block in blocks
            ):
                blocks.extend(json.loads(row["blocks"]))
                blocks.sort(key=lambda block: block.get("created_at") or "")
            break
    return messages


def _turns(
    messages: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[list[tuple[dict[str, Any], dict[str, Any]]]]:
    turns: list[list[tuple[dict[str, Any], dict[str, Any]]]] = []
    for item in messages:
        if not turns or item[0].get("role") == "user":
            turns.append([])
        turns[-1].append(item)
    return turns


def _scroll_state(
    state: dict[str, Any],
    selected: list[tuple[dict[str, Any], dict[str, Any]]],
    rows: list[dict[str, Any]],
    compressed: bool,
) -> dict[str, Any]:
    original = (state.get("agent") or {}).get("scroll") or {}
    index = deepcopy(original.get("index") or {})
    if not compressed:
        index["tiers"] = []
    by_call = {
        row["tool_call_id"]: row
        for row in rows
        if row["kind"] == "tool_result" and row["tool_call_id"]
    }
    values: dict[str, Any] = {
        "persisted_ids": [],
        "persisted_tcids": [],
        "seen_tool_result_ids": [],
        "seen_thinking_block_ids": [],
        "folded_thinking_block_ids": [],
        "seq_by_tcid": {},
        "synthetic_ids": [],
        "seq_by_id": {},
        "model_turn_seq": {},
        "model_turn_nblk": {},
        "leaf_by_id": {},
        "index": index,
        "continuation_summary": (
            deepcopy(original.get("continuation_summary"))
            if compressed else None
        ),
        "summary_update_failed": False,
    }
    for raw, row in selected:
        mid = raw["id"]
        seq = int(row["seq"])
        values["persisted_ids"].append(mid)
        values["model_turn_seq"][mid] = seq
        values["model_turn_nblk"][mid] = len(json.loads(row["blocks"]))
        hi = seq
        for block in raw.get("content") or []:
            if block.get("type") == "tool_result":
                call_id = block.get("id")
                result = by_call.get(call_id)
                if result is not None:
                    hi = max(hi, int(result["seq"]))
                    values["persisted_tcids"].append(call_id)
                    values["seen_tool_result_ids"].append(call_id)
                    values["seq_by_tcid"][call_id] = int(result["seq"])
            elif block.get("type") == "thinking" and block.get("id"):
                values["seen_thinking_block_ids"].append(block["id"])
        values["seq_by_id"][mid] = [seq, hi]
        if row["headline"]:
            values["leaf_by_id"][mid] = [seq, row["headline"]]
    if compressed:
        values["synthetic_ids"] = list(original.get("synthetic_ids") or [])
    return values


def read_legacy_timeline(
    *,
    path: Path,
    session_id: str,
    state: dict[str, Any],
    fallback: list[Message],
) -> tuple[list[Message], Iterator[dict[str, Any]]]:
    """Return complete display history and earlier approximate states."""
    rows = _rows(path, session_id)
    messages = _message_rows(rows, state)
    if not messages:
        return fallback, iter(())
    turns = _turns(messages)
    converted = agentscope_msg_to_message([
        Msg.model_validate(raw) for raw, _row in messages
    ])
    exact_groups: dict[str, list[Message]] = {}
    for message in fallback:
        original_id = (message.metadata or {}).get("original_id")
        if original_id:
            exact_groups.setdefault(str(original_id), []).append(message)
    display: list[Message] = []
    handled: set[str] = set()
    for message in converted:
        original_id = str((message.metadata or {}).get("original_id") or "")
        if original_id in handled:
            continue
        group = exact_groups.get(original_id)
        if group:
            display.extend(group)
            handled.add(original_id)
        else:
            display.append(message)
    for original_id, group in exact_groups.items():
        if original_id not in handled:
            display.extend(group)
    return display, _approximate_states(state, turns, rows)


def _approximate_states(state, turns, rows):
    """Build one boundary at a time without retaining every context prefix."""
    agent = state.get("agent") or {}
    final_context = (agent.get("state") or {}).get("context") or []
    synthetic = set((agent.get("scroll") or {}).get("synthetic_ids") or [])
    covered = 0
    for tier in ((agent.get("scroll") or {}).get("index") or {}).get(
        "tiers", []
    ):
        for block in tier:
            covered = max(covered, int(block.get("seq_hi") or 0))

    prefix: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for turn in turns[:-1]:
        prefix.extend(turn)
        boundary = max(int(row["seq"]) for _raw, row in prefix)
        compressed = covered > 0 and boundary > covered
        current = deepcopy({
            **state,
            "agent": {
                **agent,
                "state": {**agent["state"], "context": []},
                "scroll": {},
            },
        })
        selected = [item for item in prefix if item[0]["id"]]
        if compressed:
            selected_ids = {raw["id"] for raw, _row in selected}
            context = [
                deepcopy(item)
                for item in final_context
                if item.get("id") in synthetic | selected_ids
            ]
            live_ids = {item.get("id") for item in context} - synthetic
            scroll_selected = [
                item for item in selected if item[0]["id"] in live_ids
            ]
        else:
            context = [deepcopy(raw) for raw, _row in selected]
            current["agent"]["state"]["summary"] = ""
            scroll_selected = selected
        current["agent"]["state"]["context"] = context
        current["agent"]["scroll"] = _scroll_state(
            state, scroll_selected, rows, compressed
        )
        last_assistant = next(
            (raw["id"] for raw, _row in reversed(selected)
             if raw.get("role") == "assistant"),
            None,
        )
        if last_assistant:
            current["agent"]["state"]["reply_context"]["reply_id"] = (
                last_assistant
            )
        yield current
