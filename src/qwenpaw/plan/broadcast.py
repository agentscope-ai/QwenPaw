# -*- coding: utf-8 -*-
"""SSE broadcast for plan updates.

Minimal implementation: a global dict mapping agent IDs to sets of
``asyncio.Queue``. No scoping, no tickets, no auth.

Also maintains a live plan state cache so API endpoints can serve
the current plan even before the session file is written.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_queues: dict[str, set[asyncio.Queue]] = {}

# Outer key: agent_id.  Inner key: session_id.
_live_plan_cache: dict[str, dict[str, dict[str, Any] | None]] = {}


def register_sse_client(agent_id: str) -> asyncio.Queue:
    """Register a new SSE client for *agent_id* and return its queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _queues.setdefault(agent_id, set()).add(q)
    logger.debug(
        "SSE client registered for agent %s (total=%d)",
        agent_id,
        len(_queues[agent_id]),
    )
    return q


def unregister_sse_client(agent_id: str, q: asyncio.Queue) -> None:
    """Unregister an SSE client queue for *agent_id*."""
    clients = _queues.get(agent_id)
    if clients is not None:
        clients.discard(q)
        if not clients:
            del _queues[agent_id]
    logger.debug("SSE client unregistered for agent %s", agent_id)


def get_live_plan(
    agent_id: str,
    session_id: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Return ``(found, plan_data)`` from the live cache.

    When *session_id* is given, returns only a match for that session.
    When omitted, returns any cached plan for the agent.
    """
    sessions = _live_plan_cache.get(agent_id)
    if sessions is None:
        return False, None
    if session_id is not None:
        if session_id not in sessions:
            return False, None
        return True, sessions[session_id]
    for data in sessions.values():
        return True, data
    return False, None


def clear_live_plan(agent_id: str, session_id: str | None = None) -> None:
    """Remove the cached live plan state."""
    if session_id is None:
        _live_plan_cache.pop(agent_id, None)
    else:
        sessions = _live_plan_cache.get(agent_id)
        if sessions:
            sessions.pop(session_id, None)
            if not sessions:
                _live_plan_cache.pop(agent_id, None)


def broadcast_plan_update(
    agent_id: str,
    payload: dict[str, Any],
    session_id: str | None = None,
) -> None:
    """Push *payload* to all SSE clients subscribed to *agent_id*.

    Also updates the live plan cache so API polling can serve it.
    Silently drops messages for queues that are full.
    """
    if payload.get("type") == "plan_update":
        sid = session_id or ""
        sessions = _live_plan_cache.setdefault(agent_id, {})
        plan_data = payload.get("plan")
        sessions[sid] = plan_data
        logger.debug(
            "Live cache updated: agent=%s session=%r has_plan=%s",
            agent_id,
            sid,
            plan_data is not None,
        )

    clients = _queues.get(agent_id)
    if not clients:
        return
    enriched = {**payload, "session_id": session_id} if session_id else payload
    for q in list(clients):
        try:
            q.put_nowait(enriched)
        except asyncio.QueueFull:
            logger.warning(
                "SSE queue full for agent %s, dropping message",
                agent_id,
            )
