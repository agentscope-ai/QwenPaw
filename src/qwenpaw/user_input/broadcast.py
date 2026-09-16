# -*- coding: utf-8 -*-
"""SSE broadcast helpers for structured user input requests."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..runtime_status.scope import event_scope

logger = logging.getLogger(__name__)

_queues: dict[tuple[str, str | None], set[asyncio.Queue]] = {}


def register_sse_client(agent_id: str, *, user_id: str | None = None) -> asyncio.Queue:
    """Register a user-input SSE client for *agent_id*."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _queues.setdefault(event_scope(agent_id, user_id), set()).add(q)
    return q


def unregister_sse_client(
    agent_id: str, q: asyncio.Queue, *, user_id: str | None = None
) -> None:
    """Unregister a previously registered SSE client."""
    clients = _queues.get(event_scope(agent_id, user_id))
    if clients is not None:
        clients.discard(q)
        if not clients:
            del _queues[event_scope(agent_id, user_id)]


def broadcast_user_input_update(
    agent_id: str, payload: dict[str, Any], *, user_id: str | None = None
) -> None:
    """Push a user-input update to all subscribed clients for *agent_id*."""
    clients = _queues.get(event_scope(agent_id, user_id))
    if not clients:
        return
    for q in list(clients):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "User input SSE queue full for agent %s, dropping message",
                agent_id,
            )
