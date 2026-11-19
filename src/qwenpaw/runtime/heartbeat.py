# -*- coding: utf-8 -*-
"""SSE heartbeat wrapper for async iterators."""
from __future__ import annotations

import asyncio
from contextvars import copy_context

HEARTBEAT_INTERVAL_SECONDS = 25.0
_HEARTBEAT_TICK = object()


async def _iter_with_heartbeat(source_iter, interval: float):
    """Wrap an async-iter so it yields ``_HEARTBEAT_TICK`` on idle.

    Keep the pending read alive across idle ticks, including while waiting
    for a person's answer. Exceptions from the producer reach its caller.
    """
    context = copy_context()
    pending = None

    async def advance():
        return await anext(source_iter)

    try:
        while True:
            if pending is None:
                # 每次读取和关闭都在同一份运行上下文中，避免令牌跨上下文重置。
                pending = asyncio.create_task(advance(), context=context)
            done, _ = await asyncio.wait([pending], timeout=interval)
            if not done:
                yield _HEARTBEAT_TICK
                continue
            try:
                value = pending.result()
            except StopAsyncIteration:
                pending = None
                return
            pending = None
            yield value
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if hasattr(source_iter, "aclose"):
            async def close():
                await source_iter.aclose()
            await asyncio.create_task(close(), context=context)
