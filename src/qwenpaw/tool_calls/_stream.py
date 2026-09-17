# -*- coding: utf-8 -*-
"""Fan-out notifier for live tool output subscribers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

_SENTINEL = object()


@dataclass
class ToolStream:
    """Pure fan-out notifier. Holds no chunk storage of its own.

    Uses copy-on-write for ``_subscribers`` to avoid mutation during
    concurrent ``asyncio.gather`` in ``append``/``close``.
    """

    tool_call_id: str
    session_id: str
    _subscribers: tuple[asyncio.Queue[Any], ...] = ()
    _is_closed: bool = False

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    def add_subscriber(self, queue: asyncio.Queue[Any]) -> None:
        self._subscribers = (*self._subscribers, queue)

    def remove_subscriber(self, queue: asyncio.Queue[Any]) -> None:
        self._subscribers = tuple(
            q for q in self._subscribers if q is not queue
        )

    async def append(self, chunk: Any) -> None:
        if self._is_closed:
            return
        subs = self._subscribers
        if subs:
            await asyncio.gather(
                *(q.put(chunk) for q in subs),
                return_exceptions=True,
            )

    async def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        subs = self._subscribers
        if subs:
            await asyncio.gather(
                *(q.put(_SENTINEL) for q in subs),
                return_exceptions=True,
            )

    async def subscribe(self) -> AsyncIterator[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self.add_subscriber(queue)
        if self._is_closed:
            await queue.put(_SENTINEL)
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    return
                yield item
        finally:
            self.remove_subscriber(queue)
