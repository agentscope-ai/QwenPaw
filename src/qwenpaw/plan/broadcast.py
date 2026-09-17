# -*- coding: utf-8 -*-
"""SSE broadcast and live cache for plan updates."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_queues: dict[str, set[asyncio.Queue]] = {}
_live_plan_cache: dict[str, dict[str, dict[str, Any] | None]] = {}


def register_sse_client(agent_id: str) -> asyncio.Queue:
    """Register an SSE client for an agent and return its bounded queue."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _queues.setdefault(agent_id, set()).add(queue)
    logger.debug(
        "SSE client registered for agent %s (total=%d)",
        agent_id,
        len(_queues[agent_id]),
    )
    return queue


def unregister_sse_client(agent_id: str, queue: asyncio.Queue) -> None:
    """Unregister a previously registered SSE client queue."""
    clients = _queues.get(agent_id)
    if clients is not None:
        clients.discard(queue)
        if not clients:
            del _queues[agent_id]
    logger.debug("SSE client unregistered for agent %s", agent_id)


def get_live_plan(
    agent_id: str,
    session_id: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Return whether a cached plan exists and its serialized state."""
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
    """Clear cached plan state for an agent or one of its sessions."""
    if session_id is None:
        _live_plan_cache.pop(agent_id, None)
        return

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
    """Update the live cache and publish a plan event to SSE subscribers."""
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
    for queue in list(clients):
        try:
            queue.put_nowait(enriched)
        except asyncio.QueueFull:
            logger.warning(
                "SSE queue full for agent %s, dropping message",
                agent_id,
            )
