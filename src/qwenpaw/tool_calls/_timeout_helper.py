# -*- coding: utf-8 -*-
"""Cooperative timeout helpers for built-in tools."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._ctxvars import get_call_context

logger = logging.getLogger(__name__)


async def cancellable_wait(
    coro_or_task: Any,
    *,
    fallback_secs: float | None = None,
) -> Any:
    """Run a coroutine until completion or ctx.cancel_event fires.

    Replaces ``asyncio.wait_for(coro, timeout=X)`` in built-in tools.

    With a manager-injected ctx: waits on (coro, ctx.cancel_event);
    manager's monitor loop watches ctx.deadline and sets cancel_event
    when it elapses. Runtime /extend-deadline pushes deadline forward.

    Without a ctx (SDK direct call / unit test): degrades to plain
    ``asyncio.wait_for(coro, timeout=fallback_secs)``.
    """
    ctx = get_call_context()

    if ctx is None:
        if fallback_secs is None:
            return await coro_or_task
        return await asyncio.wait_for(coro_or_task, timeout=fallback_secs)

    task = (
        coro_or_task
        if isinstance(coro_or_task, asyncio.Task)
        else asyncio.ensure_future(coro_or_task)
    )
    cancel_waiter = asyncio.create_task(ctx.cancel_event.wait())

    try:
        done, _pending = await asyncio.wait(
            {task, cancel_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancel_waiter in done:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise asyncio.CancelledError(
                f"tool cancelled by manager (reason={ctx.cancel_reason})",
            )

        return task.result()
    finally:
        if not cancel_waiter.done():
            cancel_waiter.cancel()
            try:
                await cancel_waiter
            except asyncio.CancelledError:
                pass


def effective_timeout(
    default_secs: float,
    *,
    max_amplify: float = 5.0,
) -> float:
    """Return ctx.remaining() if available, else default_secs.

    USE ONLY when calling a foreign API that REQUIRES a numeric timeout
    parameter (e.g. Playwright's ``page.wait_for_selector(timeout=ms)``).
    Most tools should prefer ``cancellable_wait()`` instead.
    """
    ctx = get_call_context()
    if ctx is None:
        return default_secs
    remaining = ctx.remaining()
    if remaining is None:
        return default_secs
    return max(0.0, min(remaining, default_secs * max_amplify))
