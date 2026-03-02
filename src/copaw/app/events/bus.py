# -*- coding: utf-8 -*-
"""EventBus — asyncio.Queue-based broadcast to SSE subscribers."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import AsyncGenerator, Optional, Set

from .types import Event

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 256


class EventBus:
    """Broadcast events to all subscribers via per-subscriber queues.

    Usage::

        bus = EventBus()
        bus.emit(Event(type="agent.tool_call", data={...}))

        async for event in bus.subscribe(event_types={"agent.tool_call"}):
            print(event)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[Event]] = {}
        self._lock = asyncio.Lock()

    def emit(self, event: Event) -> None:
        """Broadcast *event* to every subscriber.

        If a subscriber's queue is full the oldest event is discarded
        to prevent slow consumers from blocking the emitter.
        """
        for sid, q in list(self._subscribers.items()):
            try:
                if q.full():
                    # Discard oldest to make room.
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(event)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to deliver event to subscriber %s", sid)

    async def subscribe(
        self,
        event_types: Optional[Set[str]] = None,
    ) -> AsyncGenerator[Event, None]:
        """Yield events as they arrive.

        Args:
            event_types: If provided, only yield events whose ``type``
                         is in this set. ``None`` means all events.

        The subscriber is automatically removed when the generator is
        closed (e.g. when the SSE connection drops).
        """
        sid = uuid.uuid4().hex[:12]
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        async with self._lock:
            self._subscribers[sid] = q
        logger.debug("Subscriber %s connected (filter=%s)", sid, event_types)
        try:
            while True:
                event = await q.get()
                if event_types and event.type not in event_types:
                    continue
                yield event
        finally:
            async with self._lock:
                self._subscribers.pop(sid, None)
            logger.debug("Subscriber %s disconnected", sid)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# ── module-level singleton ───────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Return the global EventBus singleton (created on first call)."""
    global _bus  # noqa: PLW0603
    if _bus is None:
        _bus = EventBus()
    return _bus
