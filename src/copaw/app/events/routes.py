# -*- coding: utf-8 -*-
"""SSE endpoint for real-time event streaming."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query
from starlette.requests import Request
from starlette.responses import StreamingResponse

from .bus import get_event_bus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

_HEARTBEAT_INTERVAL = 15  # seconds


async def _event_generator(
    request: Request,
    event_types: Optional[set[str]] = None,
):
    """Async generator that yields SSE-formatted events."""
    bus = get_event_bus()

    async def _stream():
        async for event in bus.subscribe(event_types=event_types):
            if await request.is_disconnected():
                break
            line = json.dumps(event.model_dump(), ensure_ascii=False)
            yield f"data: {line}\n\n"

    # Merge event stream with periodic heartbeat.
    stream = _stream()
    heartbeat_event = asyncio.Event()

    async def _heartbeat_ticker():
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            heartbeat_event.set()

    ticker = asyncio.create_task(_heartbeat_ticker())
    try:
        while True:
            if await request.is_disconnected():
                break

            # Wait for either an event or heartbeat timeout.
            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(stream.__anext__()),
                    asyncio.create_task(heartbeat_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                try:
                    result = task.result()
                except StopAsyncIteration:
                    return
                if isinstance(result, str):
                    # Event data line.
                    yield result
                else:
                    # Heartbeat triggered.
                    heartbeat_event.clear()
                    yield ": ping\n\n"
            # Cancel remaining tasks.
            for task in _:
                task.cancel()
    finally:
        ticker.cancel()
        await stream.aclose()


@router.get("")
async def sse_events(
    request: Request,
    types: Optional[str] = Query(
        default=None,
        description="Comma-separated event types to filter",
    ),
):
    """Server-Sent Events stream.

    Connect via ``GET /api/events?types=agent.tool_call,cron.triggered``.
    A ``: ping`` comment is sent every 15 s to keep the connection alive.
    """
    event_types = None
    if types:
        event_types = {t.strip() for t in types.split(",") if t.strip()}

    return StreamingResponse(
        _event_generator(request, event_types),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
