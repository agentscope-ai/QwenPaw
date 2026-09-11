# -*- coding: utf-8 -*-
"""Process-local browser handoff signals consumed by the ReAct loop."""

from __future__ import annotations

_PENDING: dict[str, dict[str, str]] = {}


def set_pending(session_id: str, info: dict[str, str]) -> None:
    """Record a browser handoff until the stop gate consumes it."""
    _PENDING[session_id] = info


def take_pending(session_id: str) -> dict[str, str] | None:
    """Consume the handoff pending for a session, if any."""
    return _PENDING.pop(session_id, None)


def has_pending(session_id: str) -> bool:
    """Return whether a session has a handoff waiting for its gate."""
    return session_id in _PENDING
