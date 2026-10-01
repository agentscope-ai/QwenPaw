# -*- coding: utf-8 -*-
"""Merge middleware-injected events into an agent's reasoning stream.

A plain ``async for`` over the reasoning generator only regains control
when it yields, so anything a middleware queues during a long ``await``
(an advisor writing its plan) would stay invisible until the model
produced its first token. :func:`merge_injected_events` awaits the next
inner event and the next queued event together and yields whichever
arrives first. Queued events are always flushed before an inner event,
so an injected exchange precedes the model output it shaped.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator


def _drain(queue: "asyncio.Queue[Any]") -> Any:
    while not queue.empty():
        yield queue.get_nowait()


async def merge_injected_events(
    inner: AsyncIterator[Any],
    queue: "asyncio.Queue[Any]",
) -> AsyncIterator[Any]:
    """Yield ``inner``'s events, interleaving ``queue``'s events live."""
    next_task: asyncio.Task[Any] | None = None
    get_task: asyncio.Task[Any] | None = None
    try:
        while True:
            for queued in _drain(queue):
                yield queued
            if next_task is None:
                next_task = asyncio.ensure_future(inner.__anext__())
            if get_task is None:
                get_task = asyncio.ensure_future(queue.get())
            done, _pending = await asyncio.wait(
                {next_task, get_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if get_task in done:
                evt, get_task = get_task.result(), None
                yield evt
            if next_task in done:
                task, next_task = next_task, None
                try:
                    evt = task.result()
                except StopAsyncIteration:
                    return
                for queued in _drain(queue):
                    yield queued
                yield evt
    finally:
        if get_task is not None:
            get_task.cancel()
        if next_task is not None and not next_task.done():
            # Torn down mid-step (interrupted, or the consumer stopped
            # early). Pass the cancellation on so the inner generator's
            # own cleanup runs, as it would under a plain ``async for``.
            next_task.cancel()
            with contextlib.suppress(BaseException):
                await next_task
        if get_task is not None:
            with contextlib.suppress(BaseException):
                await get_task
        # Close the inner generator eagerly. A plain ``async for`` that is
        # left early relies on garbage collection for this.
        with contextlib.suppress(BaseException):
            await inner.aclose()
