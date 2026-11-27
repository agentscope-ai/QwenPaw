# -*- coding: utf-8 -*-
"""Process-local store for pending ``/steer`` guidance.

``/steer`` is dispatched as its own request, before the agent turn it is
meant to influence. ``ctx.extras`` is rebuilt per request, so the guidance
cannot survive in it. This module keeps a small per-session hand-off buffer
that :mod:`qwenpaw.steer.hook` drains exactly once.

Entries expire so an abandoned ``/steer`` cannot leak into a much later
turn.
"""
from __future__ import annotations

import threading
import time

#: Guidance older than this is discarded rather than injected.
TTL_SECONDS = 600

_lock = threading.Lock()
_pending: dict[str, tuple[str, float]] = {}


def put_guidance(session_id: str, guidance: str) -> None:
    """Record *guidance* to be picked up by the next agent turn."""
    if not session_id:
        return
    with _lock:
        _pending[session_id] = (guidance, time.time())


def pop_guidance(session_id: str) -> tuple[str, float] | None:
    """Take and clear pending guidance for *session_id*.

    Returns ``(guidance, timestamp)`` or ``None`` when nothing is pending
    or the entry has expired.
    """
    if not session_id:
        return None
    with _lock:
        entry = _pending.pop(session_id, None)
    if entry is None:
        return None
    guidance, ts = entry
    if time.time() - ts > TTL_SECONDS:
        return None
    return guidance, ts


def clear(session_id: str) -> None:
    """Drop any pending guidance (used by tests)."""
    with _lock:
        _pending.pop(session_id, None)


__all__ = ["TTL_SECONDS", "clear", "pop_guidance", "put_guidance"]
