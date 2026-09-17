# -*- coding: utf-8 -*-
"""Lightweight runtime status cache and SSE broadcast."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from .scope import event_scope

logger = logging.getLogger(__name__)

_queues: dict[tuple[str, str | None], set[asyncio.Queue]] = {}
_status_cache: dict[tuple[str, str | None], dict[str, dict[str, Any] | None]] = {}


def register_sse_client(agent_id: str, *, user_id: str | None = None) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _queues.setdefault(event_scope(agent_id, user_id), set()).add(q)
    return q


def unregister_sse_client(
    agent_id: str, q: asyncio.Queue, *, user_id: str | None = None
) -> None:
    clients = _queues.get(event_scope(agent_id, user_id))
    if clients is not None:
        clients.discard(q)
        if not clients:
            del _queues[event_scope(agent_id, user_id)]


def get_runtime_status(
    agent_id: str,
    session_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    return _status_cache.get(event_scope(agent_id, user_id), {}).get(session_id)


def clear_runtime_status(
    agent_id: str, session_id: str, *, user_id: str | None = None
) -> None:
    sessions = _status_cache.get(event_scope(agent_id, user_id))
    if not sessions:
        return
    sessions.pop(session_id, None)
    if not sessions:
        _status_cache.pop(event_scope(agent_id, user_id), None)


def broadcast_runtime_status(
    agent_id: str,
    *,
    session_id: str,
    root_session_id: str | None = None,
    chat_id: str | None = None,
    stage: str,
    status: str = "running",
    message: str = "",
    detail: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    try:
        scope = event_scope(agent_id, user_id)
    except ValueError:
        return
    if not session_id:
        return
    # A completed tool is terminal for its progress card.  Normalize legacy
    # callers that still send ``status=running`` so a finished command can
    # never be retained in the process cache indefinitely.
    if stage == "tool_completed":
        status = "completed"
    payload = {
        "type": "runtime_status",
        "event_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "session_id": session_id,
        "root_session_id": root_session_id or session_id,
        "chat_id": chat_id,
        "stage": stage,
        "status": status,
        "message": message,
        "detail": detail or {},
        "ts": time.time(),
    }
    if status in {"idle", "completed"}:
        clear_runtime_status(agent_id, session_id, user_id=user_id)
    else:
        _status_cache.setdefault(scope, {})[session_id] = payload

    clients = _queues.get(event_scope(agent_id, user_id))
    if not clients:
        return
    for q in list(clients):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "Runtime status SSE queue full for agent %s",
                agent_id,
            )
