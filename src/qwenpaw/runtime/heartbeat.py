# -*- coding: utf-8 -*-
"""SSE heartbeat wrapper for async iterators."""
from __future__ import annotations

import asyncio

HEARTBEAT_INTERVAL_SECONDS = 25.0
_HEARTBEAT_TICK = object()


async def _iter_with_heartbeat(source_iter, interval: float):
    """Wrap an async-iter so it yields ``_HEARTBEAT_TICK`` on idle.

    Uses ``asyncio.shield`` so that ``wait_for``'s cancellation on timeout
    does NOT cancel the underlying ``__anext__()`` task — that task lives
    across heartbeats and is awaited again on the next loop iteration.
    Without shielding, a long approval wait would lose every heartbeat's
    worth of pending state.
    """
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(source_iter.__anext__())
            try:
                value = await asyncio.wait_for(
                    asyncio.shield(pending),
                    timeout=interval,
                )
            except asyncio.TimeoutError:
                yield _HEARTBEAT_TICK
                continue
            except StopAsyncIteration:
                pending = None
                return
            pending = None
            yield value
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
