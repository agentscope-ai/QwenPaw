# -*- coding: utf-8 -*-
"""In-memory store for console channel push messages (e.g. cron text).

Bounded: at most _MAX_MESSAGES kept; messages older than _MAX_AGE_SECONDS
are dropped when reading. Frontend dedupes by id and caps its seen set.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List

# Single list: each item has id, text, ts, session_id and optional metadata.
# Bounded by count and age.
_list: List[Dict[str, Any]] = []
_lock = asyncio.Lock()
_MAX_AGE_SECONDS = 60
_MAX_MESSAGES = 500


async def append(session_id: str, text: str, *, sticky: bool = False) -> None:
    """Append a message (bounded: oldest dropped if over _MAX_MESSAGES)."""
    if not session_id or not text:
        return
    async with _lock:
        _list.append(
            {
                "id": str(uuid.uuid4()),
                "text": text,
                "sticky": sticky,
                "ts": time.time(),
                "session_id": session_id,
            },
        )
        if len(_list) > _MAX_MESSAGES:
            _list.sort(key=lambda m: m["ts"])
            del _list[: len(_list) - _MAX_MESSAGES]


async def take(session_id: str) -> List[Dict[str, Any]]:
    """Return and remove all non-expired messages for the session.

    Expired messages (older than ``_MAX_AGE_SECONDS``) are silently
    discarded so callers never receive stale push notifications.
    """
    if not session_id:
        return []
    cutoff = time.time() - _MAX_AGE_SECONDS
    async with _lock:
        out = [
            m
            for m in _list
            if m.get("session_id") == session_id and m["ts"] >= cutoff
        ]
        # Remove taken messages *and* any expired ones to bound memory.
        _list[:] = [
            m
            for m in _list
            if m.get("session_id") != session_id and m["ts"] >= cutoff
        ]
        return _strip_ts(out)


async def take_all() -> List[Dict[str, Any]]:
    """Return and remove all non-expired messages.

    Messages older than ``_MAX_AGE_SECONDS`` are dropped instead of
    being returned.
    """
    cutoff = time.time() - _MAX_AGE_SECONDS
    async with _lock:
        out = [m for m in _list if m["ts"] >= cutoff]
        _list.clear()
        return _strip_ts(out)


def _strip_ts(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": m["id"],
            "text": m["text"],
            "sticky": bool(m.get("sticky", False)),
        }
        for m in msgs
    ]


async def get_recent(
    max_age_seconds: int = _MAX_AGE_SECONDS,
) -> List[Dict[str, Any]]:
    """
    Return recent messages (not consumed). Drop older than max_age_seconds
    from store to bound memory.
    """
    now = time.time()
    cutoff = now - max_age_seconds
    async with _lock:
        out = [m for m in _list if m["ts"] >= cutoff]
        _list[:] = out
        return _strip_ts(out)
