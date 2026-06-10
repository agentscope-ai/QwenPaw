# -*- coding: utf-8 -*-
"""In-process SSE stream for a2a_call tool progress.

a2a_call pushes incremental events into start_stream() queue while it
runs.  The /a2a/call/stream REST endpoint reads from read_stream_sse()
and forwards them to the frontend as Server-Sent Events, enabling
real-time display without relying on QwenPaw to forward intermediate
ToolResponse yields.

Only one a2a_call runs at a time (the LLM is blocked until it returns),
so a single module-level queue is safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)

_queue: asyncio.Queue | None = None


def start_stream() -> asyncio.Queue:
    """Create a fresh queue for a new call.  Called by a2a_call at startup."""
    global _queue
    _queue = asyncio.Queue(maxsize=1000)
    return _queue


def get_stream() -> asyncio.Queue | None:
    """Return the current stream queue (if any)."""
    return _queue


def finish_stream() -> None:
    """Signal the end of the stream by putting a None sentinel."""
    global _queue
    if _queue is not None:
        try:
            _queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        _queue = None


def push(data: dict) -> None:
    """Push an event dict into the current stream queue."""
    global _queue
    if _queue is not None:
        try:
            _queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("A2A stream queue full, dropping event")


async def read_stream_sse() -> AsyncIterator[str]:
    """Yield SSE-formatted strings until the call finishes.

    Waits up to 3 s for the call to start (handles the race where the
    frontend connects before a2a_call has initialised the queue).
    """
    for _ in range(30):
        if _queue is not None:
            break
        await asyncio.sleep(0.1)

    queue = _queue
    if queue is None:
        msg = json.dumps({"done": True, "error": "no active call"})
        yield f"data: {msg}\n\n"
        return

    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=60.0)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue

        if item is None:
            yield f"data: {json.dumps({'done': True})}\n\n"
            break

        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
