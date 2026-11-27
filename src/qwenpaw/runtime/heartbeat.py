# -*- coding: utf-8 -*-
"""SSE heartbeat wrapper for async iterators."""

from __future__ import annotations

import asyncio
import logging

from ..utils.io_utils import run_async_to_completion

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 25.0
_HEARTBEAT_TICK = object()


async def _iter_with_heartbeat(source_iter, interval: float):
    """Wrap an async-iter so it yields ``_HEARTBEAT_TICK`` on idle.

    Keep one ``__anext__()`` task alive across heartbeat timeouts. Using
    ``asyncio.wait`` distinguishes an idle wait from ``TimeoutError`` raised
    by the source iterator, so source exceptions propagate unchanged.
    """
    pending = None
    failure = None
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

            completed, pending = pending, None
            try:
                value = completed.result()
            except StopAsyncIteration:
                return

            yield value
    except BaseException as exc:
        failure = exc
        raise
    finally:

        async def close_source():
            try:
                if pending is not None:
                    if not pending.done():
                        pending.cancel()
                    try:
                        await pending
                    except (asyncio.CancelledError, StopAsyncIteration):
                        pass
            finally:
                close = getattr(source_iter, "aclose", None)
                if close is not None:
                    await close()

        try:
            await run_async_to_completion(close_source())
        except BaseException:
            if failure is None or isinstance(
                failure,
                (asyncio.CancelledError, GeneratorExit),
            ):
                raise
            logger.warning("Heartbeat cleanup failed", exc_info=True)
