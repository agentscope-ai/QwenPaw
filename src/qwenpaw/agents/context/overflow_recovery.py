# -*- coding: utf-8 -*-
"""One recovery boundary across model calls and stream consumption.

The agent supplies recovery that classifies the error, compacts context,
rebuilds input, and calls the model again. This module owns the retry boundary
and stream lifecycle; it does not rewrap the recovery response. A caller may
return an already wrapped retry with a shared budget for multiple attempts.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

from ...providers.stream_progress import has_meaningful_stream_content
from ...runtime.turn_context import current_run_streams


async def call_with_overflow_recovery(
    call_model: Callable[..., Awaitable[Any]],
    recover: Callable[[Exception], Awaitable[Any]],
    *,
    max_recoveries: int = 2,
    **kwargs: Any,
) -> Any:
    """Recover errors from invocation or pre-output stream consumption.

    Recovery is bounded *and shared*. A 413 that omits historical media can
    be followed by a second 413 about the media in the active turn, and that
    second refusal has to reach the same budget — otherwise it ends the turn
    with the active image still at its original size. Retrying without a cap
    would let a provider loop forever, so the budget counts the recoveries.
    """
    budget = [max_recoveries]

    async def _recover(exc: Exception) -> Any:
        # The recovery call is a model request too, and it can be refused
        # for a different part of the same request: omitting a historical
        # image removes the body-size failure, then the provider rejects
        # the still-oversized active image. Keeping the loop here lets that
        # second refusal spend the remaining budget instead of ending the
        # turn.
        while True:
            if budget[0] <= 0:
                raise exc
            budget[0] -= 1
            try:
                return await recover(exc)
            except Exception as retry_exc:
                # Re-raising the same exception means the recovery gave up
                # (for example, context recovery could not change the
                # input). Retrying it would repeat work that just decided
                # there is nothing to do.
                if retry_exc is exc:
                    raise
                exc = retry_exc
                if budget[0] <= 0:
                    raise

    try:
        response = await call_model(**kwargs)
    except Exception as exc:
        response = await _recover(exc)
        # The retry of a failed invocation is a stream too. Without this the
        # second refusal of the same request — omitting history first, then
        # the active image — ended the turn instead of reaching the budget.
        if inspect.isasyncgen(response):
            response = _stream_with_overflow_recovery(
                response,
                _recover,
                budget,
            )
    else:
        if inspect.isasyncgen(response):
            response = _stream_with_overflow_recovery(
                response,
                _recover,
                budget,
            )
    if inspect.isasyncgen(response):
        if owned := current_run_streams.get():
            owned.retain(response)
    return response


async def _stream_with_overflow_recovery(
    stream: AsyncGenerator[Any, None],
    recover: Callable[[Exception], Awaitable[Any]],
    budget: list[int] | None = None,
) -> AsyncGenerator[Any, None]:
    """Close consumed streams and never replay meaningful model output."""
    emitted = False
    try:
        async with aclosing(stream):
            async for chunk in stream:
                emitted = emitted or has_meaningful_stream_content(
                    chunk.content,
                )
                yield chunk
        return
    except Exception as exc:
        if emitted:
            raise
        response = await recover(exc)
    # Consume the retry directly so both failure phases share one attempt.
    # The retry is covered as well: a second refusal about a different part
    # of the same request must recover once more, from the same budget.
    if inspect.isasyncgen(response) and budget:
        response = _stream_with_overflow_recovery(response, recover, budget)
    if inspect.isasyncgen(response):
        async with aclosing(response):
            async for chunk in response:
                yield chunk
    else:
        yield response
