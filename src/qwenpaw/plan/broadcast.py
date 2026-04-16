# -*- coding: utf-8 -*-
"""SSE broadcast bus for real-time plan updates.

Each SSE client registers an ``asyncio.Queue`` keyed by agent_id.
The plan-change hook pushes updates into all registered queues so
every connected SSE client receives real-time plan state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_plan_update_queues: dict[str, set[asyncio.Queue[Any]]] = {}

# Bound per-client queues so a slow / stuck consumer cannot grow
# memory indefinitely.  256 plan-update events is generous for any
# realistic console session; older events are dropped with a warning.
_SSE_QUEUE_MAXSIZE = 256


def register_sse_client(agent_id: str) -> asyncio.Queue[Any]:
    """Register a new SSE client queue for *agent_id*."""
    q: asyncio.Queue[Any] = asyncio.Queue(
        maxsize=_SSE_QUEUE_MAXSIZE,
    )
    _plan_update_queues.setdefault(agent_id, set()).add(q)
    return q


def unregister_sse_client(agent_id: str, q: asyncio.Queue[Any]) -> None:
    """Remove a client queue when the SSE connection closes."""
    clients = _plan_update_queues.get(agent_id)
    if clients:
        clients.discard(q)
        if not clients:
            del _plan_update_queues[agent_id]


def broadcast_plan_update(agent_id: str, payload: dict | None) -> None:
    """Push *payload* to every SSE client listening for *agent_id*.
    *payload* may be ``None`` when the active plan is cleared.
    This is called from the plan-change hook inside the agent's async
    context, so it must be non-blocking.
    """
    clients = _plan_update_queues.get(agent_id)
    if not clients:
        return
    for q in clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "Plan SSE queue full for agent %s, dropping update",
                agent_id,
            )
