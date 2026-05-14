# -*- coding: utf-8 -*-
"""In-memory context window usage snapshots keyed by session."""

from __future__ import annotations

from typing import Any


_usage_by_session: dict[str, dict[str, Any]] = {}


def record_context_usage(
    session_id: str,
    *,
    total_tokens: int,
    max_input_length: int,
    total_messages: int | None = None,
) -> dict[str, Any] | None:
    """Store the latest context usage snapshot for a session."""
    if not session_id:
        return None

    safe_total = max(0, int(total_tokens or 0))
    safe_max = max(0, int(max_input_length or 0))
    pct = (safe_total / safe_max * 100) if safe_max > 0 else 0.0

    usage: dict[str, Any] = {
        "total_tokens": safe_total,
        "max_input_length": safe_max,
        "pct": pct,
    }
    if total_messages is not None:
        usage["total_messages"] = max(0, int(total_messages))

    _usage_by_session[session_id] = usage
    return usage


def pop_context_usage_for_session(
    session_id: str,
) -> dict[str, Any] | None:
    """Return and remove the latest context usage snapshot for a session."""
    if not session_id:
        return None
    return _usage_by_session.pop(session_id, None)


def clear_context_usage() -> None:
    """Clear all recorded snapshots. Intended for tests."""
    _usage_by_session.clear()
