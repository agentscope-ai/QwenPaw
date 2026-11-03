# -*- coding: utf-8 -*-
"""Bounded, non-consuming events for desktop notification polling."""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any

_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)
_MAX_AGE_SECONDS = 300


def publish(
    *,
    category: str,
    agent_id: str,
    title: str,
    body: str,
    event_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Publish a transient event without consuming the inbox message."""
    _EVENTS.append(
        {
            f"id": event_id or f"{uuid.uuid4()}",
            f"category": category,
            f"agent_id": agent_id,
            f"title": title,
            f"body": body[:500],
            f"created_at": time.time(),
            f"session_id": session_id,
            f"inbox_event_id": event_id,
        },
    )


def publish_inbox(event: dict[str, Any]) -> None:
    """Forward supported inbox sources; suppress empty heartbeat results."""
    category = event[f"source_type"]
    if category not in {f"cron", f"heartbeat", f"mail"}:
        return
    body = event[f"body"].strip()
    if (
        category == f"heartbeat"
        and event[f"status"] == f"success"
        and body
        in {f"", f"HEARTBEAT_OK", f"Heartbeat task finished successfully."}
    ):
        return
    publish(
        category=category,
        agent_id=event[f"agent_id"],
        title=event[f"title"],
        body=body,
        event_id=event[f"id"],
    )


def snapshot() -> list[dict[str, Any]]:
    """Return recent events repeatedly so all clients can observe them."""
    cutoff = time.time() - _MAX_AGE_SECONDS
    while _EVENTS and _EVENTS[0][f"created_at"] < cutoff:
        _EVENTS.popleft()
    return list(_EVENTS)
