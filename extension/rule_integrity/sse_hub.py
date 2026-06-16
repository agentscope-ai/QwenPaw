# -*- coding: utf-8 -*-
"""In-process SSE fan-out for built-in rule integrity status events."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


class RuleIntegritySSEHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
        event_type = str(event.get("type") or "unknown")
        logger.info(
            "rule_integrity_sse_publish type=%s subscribers=%s status=%s",
            event_type,
            len(subscribers),
            event.get("status", "-"),
        )
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def close_all(self) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for queue in subscribers:
            await queue.put(None)

    @staticmethod
    def format_sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
