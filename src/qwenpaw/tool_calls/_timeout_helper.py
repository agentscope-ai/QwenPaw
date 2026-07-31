# -*- coding: utf-8 -*-
"""Cooperative timeout helpers for built-in tools."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._ctxvars import get_call_context

logger = logging.getLogger(__name__)

# Foreground offload window as a fraction of the resolved tool timeout so
# tools that arm kill_deadline to the same timeout still get a background
# phase (kill must remain strictly later than offload).
OFFLOAD_TIMEOUT_RATIO = 0.5

# After offload, ensure at least this much kill budget remains.
MIN_BACKGROUND_WINDOW_SECS = 30.0

# When ToolCallContext owns the hard kill, sandbox/HTTP layers use this
# large ceiling so ``extend_kill_deadline`` is not defeated by a frozen
# copy of the original timeout. Coordinator cancel remains the real stop.
# Tools that use this ceiling (shell / chat_with_agent) must also register
# the same value as ``max_internal_timeout_secs`` so the deadline API cannot
# accept ``no_deadline`` or extends past what the executor will honor.
COORDINATOR_OWNED_EXEC_TIMEOUT_SECS = 24 * 3600


def arm_kill_deadline(
    ctx: Any,
    secs: float,
    *,
    only_if_unset: bool = True,
) -> bool:
    """Arm ``kill_deadline`` and keep offload strictly earlier when needed.

    When the tool's hard timeout is shorter than the coordinator offload
    window, pull ``offload_deadline`` back to ``secs * OFFLOAD_TIMEOUT_RATIO``
    so kill cannot win before automatic offload — without exceeding the
    user-provided hard limit.

    Returns True when a kill deadline was written (or already present when
    *only_if_unset* is True).
    """
    if only_if_unset and ctx.kill_deadline is not None:
        return True
    if secs is None or secs < 0:
        return False

    loop = asyncio.get_running_loop()
    now = loop.time()
    desired_kill = now + secs
    ctx.kill_deadline = desired_kill
    if (
        ctx.offload_deadline is not None
        and ctx.offload_deadline >= desired_kill
    ):
        pulled = now + max(0.0, secs * OFFLOAD_TIMEOUT_RATIO)
        if pulled >= desired_kill and secs > 0:
            pulled = desired_kill - min(0.001, secs / 2.0)
        ctx.offload_deadline = pulled
        logger.debug(
            "Pulled offload_deadline before kill (%.1fs) for %s",
            secs,
            getattr(ctx, "tool_name", "?"),
        )
    ctx.deadline_changed_event.set()
    logger.debug(
        "kill_deadline set to %.1fs for %s",
        secs,
        getattr(ctx, "tool_name", "?"),
    )
    return True


async def cancellable_wait(
    coro_or_task: Any,
    *,
    fallback_secs: float | None = None,
    as_kill_deadline: bool = False,
) -> Any:
    """Run a coroutine until completion or ctx.cancel_event fires.

    When *as_kill_deadline* is True AND a ToolCallContext exists,
    *fallback_secs* is registered as ``ctx.kill_deadline`` — the
    Coordinator will enforce it across foreground and background phases,
    and it can be extended at runtime via ``extend_kill_deadline()``.

    When *as_kill_deadline* is False (default), *fallback_secs* is only
    used as a plain asyncio timeout when no ToolCallContext exists
    (SDK direct call / unit test).
    """
    ctx = get_call_context()

    if ctx is None:
        if fallback_secs is None:
            return await coro_or_task
        return await asyncio.wait_for(coro_or_task, timeout=fallback_secs)

    if as_kill_deadline and fallback_secs is not None:
        arm_kill_deadline(ctx, fallback_secs)

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
    if ctx.kill_deadline is None:
        return default_secs
    remaining = max(0.0, ctx.kill_deadline - asyncio.get_running_loop().time())
    return max(0.0, min(remaining, default_secs * max_amplify))
