# -*- coding: utf-8 -*-
"""Unified event bus for CoPaw real-time event streaming.

Provides an EventBus singleton that broadcasts events to SSE subscribers
via per-subscriber asyncio.Queue channels.
"""

from .types import Event, EventType
from .bus import EventBus, get_event_bus

__all__ = [
    "Event",
    "EventType",
    "EventBus",
    "get_event_bus",
]
