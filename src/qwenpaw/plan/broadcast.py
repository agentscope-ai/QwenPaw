# -*- coding: utf-8 -*-
"""SSE broadcast bus for real-time plan updates.

Each SSE client registers an ``asyncio.Queue`` keyed by *agent_id* (legacy) or
by *(agent_id, scope_key)* when ``scope_key`` is set (console session/channel
isolation). The plan-change hook pushes updates into matching queues.

Multi-worker: queues are process-local; see ``PLAN_SSE_MULTIWORKER.md``.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_plan_update_queues: dict[str, set[asyncio.Queue[Any]]] = {}

# Async-aware scope for the active chat session (channel + session_id).
# Set around runner query handling and HTTP plan mutations so hooks broadcast
# to the correct SSE bucket without threading request objects through hooks.
_plan_sse_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "plan_sse_scope",
    default=None,
)

_UNSET = object()

# Bound per-client queues so a slow / stuck consumer cannot grow
# memory indefinitely.  256 plan-update events is generous for any
# realistic console session; older events are dropped with a warning.
_SSE_QUEUE_MAXSIZE = 256


def plan_sse_scope_key(channel: str, session_id: str) -> str | None:
    """Return a stable scope string for SSE routing, or ``None`` if unscoped.

    When *session_id* is empty, callers should fall back to legacy *agent_id*
    only routing (same as pre-scope behaviour).
    """
    sid = (session_id or "").strip()
    if not sid:
        return None
    ch = (channel or "").strip() or "console"
    return f"{ch}:{sid}"


def _bucket_key(agent_id: str, scope_key: str | None) -> str:
    if not scope_key:
        return agent_id
    return f"{agent_id}\x1f{scope_key}"


@contextmanager
def plan_sse_scope(
    channel: str | None,
    session_id: str | None,
) -> Iterator[None]:
    """Bind broadcast_plan_update to session/channel scope for this task."""
    key = plan_sse_scope_key(channel or "", session_id or "")
    token = _plan_sse_scope.set(key)
    try:
        yield
    finally:
        _plan_sse_scope.reset(token)


def register_sse_client(
    agent_id: str,
    *,
    scope_key: str | None = None,
) -> asyncio.Queue[Any]:
    """Register a new SSE client queue for *agent_id* (optionally scoped)."""
    q: asyncio.Queue[Any] = asyncio.Queue(
        maxsize=_SSE_QUEUE_MAXSIZE,
    )
    bkey = _bucket_key(agent_id, scope_key)
    _plan_update_queues.setdefault(bkey, set()).add(q)
    return q


def unregister_sse_client(
    agent_id: str,
    q: asyncio.Queue[Any],
    *,
    scope_key: str | None = None,
) -> None:
    """Remove a client queue when the SSE connection closes."""
    bkey = _bucket_key(agent_id, scope_key)
    clients = _plan_update_queues.get(bkey)
    if clients:
        clients.discard(q)
        if not clients:
            del _plan_update_queues[bkey]


def broadcast_plan_update(
    agent_id: str,
    payload: dict | None,
    scope_key: Any = _UNSET,
) -> None:
    """Push *payload* to SSE clients for *agent_id*.

    *scope_key*:
    - When omitted, uses the current :func:`plan_sse_scope` context value
      (if any); otherwise broadcasts to the legacy *agent_id* bucket only.
    - When ``None`` is passed explicitly, only the legacy *agent_id* bucket
      receives the update.
    - When a non-empty scope is in effect (context or explicit), only that
      scoped bucket receives the update (avoids cross-session leakage on the
      shared notebook).
    """
    if scope_key is _UNSET:
        eff: str | None = _plan_sse_scope.get()
    else:
        eff = scope_key  # type: ignore[assignment]

    bk = _bucket_key(agent_id, eff)
    clients = _plan_update_queues.get(bk)
    if not clients:
        return
    for q in clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "Plan SSE queue full for bucket %s, dropping update",
                bk,
            )
