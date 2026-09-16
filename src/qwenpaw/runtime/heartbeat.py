# -*- coding: utf-8 -*-
"""SSE heartbeat wrapper for async iterators."""
from __future__ import annotations

import asyncio

HEARTBEAT_INTERVAL_SECONDS = 25.0
_HEARTBEAT_TICK = object()


async def _iter_with_heartbeat(source_iter, interval: float):
    """Wrap an async-iter so it yields ``_HEARTBEAT_TICK`` on idle.

    Keep one ``__anext__()`` task alive across heartbeat timeouts. Using
    ``asyncio.wait`` distinguishes an idle wait from ``TimeoutError`` raised
    by the source iterator, so source exceptions propagate unchanged.
    """
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(source_iter.__anext__())

            done, _ = await asyncio.wait(
                {pending},
                timeout=interval,
            )
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
