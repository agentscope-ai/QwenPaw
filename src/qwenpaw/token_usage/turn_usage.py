# -*- coding: utf-8 -*-
"""Per-turn usage metadata attached to assistant messages."""

from __future__ import annotations

from typing import Any

TURN_USAGE_META_KEY = "qwenpaw_turn_usage"


def find_turn_closing_assistant(memory: Any) -> Any | None:
    """Return the assistant message that closes the latest turn."""
    content = getattr(memory, "content", None)
    if not content:
        return None
    for msg, _marks in reversed(content):
        role = getattr(msg, "role", None)
        if role == "user":
            break
        if role == "assistant":
            return msg
    return None


def attach_turn_usage_metadata(
    memory: Any,
    turn: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
) -> bool:
    """Write turn/context usage onto the closing assistant message."""
    if turn is None and ctx is None:
        return False
    msg = find_turn_closing_assistant(memory)
    if msg is None:
        return False
    meta = getattr(msg, "metadata", None)
    if not isinstance(meta, dict):
        meta = {}
        msg.metadata = meta
    meta[TURN_USAGE_META_KEY] = {
        "usage": turn,
        "context_usage": ctx,
    }
    return True
