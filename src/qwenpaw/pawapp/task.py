# -*- coding: utf-8 -*-
"""In-memory SSE channel used by App-owned interactive streams.

Durable task submission, replay and delivery receipts live in ``pawapp.tasks``.
This channel remains available to existing Apps such as Agent Kanban.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict

logger = logging.getLogger(__name__)


class SSEChannel:
    """Async-safe Server-Sent Events channel.

    Producers call ``send_event(data)``; consumers iterate with
    ``async for event in channel``.
    """

    def __init__(self, max_buffer: int = 1000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_buffer)
        self._closed = False

    async def send_event(self, data: Dict[str, Any]) -> None:
        """Send an event to the channel (non-blocking for producer)."""
        if self._closed:
            return
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("SSEChannel buffer full, dropping event")

    def close(self) -> None:
        """Mark the channel as closed."""
        self._closed = True
        # Put a sentinel to unblock consumers
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def __aiter__(self) -> AsyncIterator[str]:
        """Yield SSE-formatted strings until channel is closed."""
        while True:
            # Check if channel is closed and queue is empty
            if self._closed and self._queue.empty():
                break

            try:
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"
                continue

            if event is None:
                # Channel closed sentinel
                break

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
