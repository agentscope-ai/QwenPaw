# -*- coding: utf-8 -*-
"""One-shot overflow recovery across model calls and stream consumption.

The agent supplies recovery that classifies the error, compacts context,
rebuilds input, and calls the model again. This module owns the retry boundary
and stream lifecycle; the recovery response is never wrapped for retry again.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

from ...providers.stream_progress import has_meaningful_stream_content


async def call_with_overflow_recovery(
    call_model: Callable[..., Awaitable[Any]],
    recover: Callable[[Exception], Awaitable[Any]],
    **kwargs: Any,
) -> Any:
    """Recover errors from invocation or pre-output stream consumption."""
    try:
        response = await call_model(**kwargs)
    except Exception as exc:
        return await recover(exc)
    if inspect.isasyncgen(response):
        return _stream_with_overflow_recovery(response, recover)
    return response


async def _stream_with_overflow_recovery(
    stream: AsyncGenerator[Any, None],
    recover: Callable[[Exception], Awaitable[Any]],
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
    if inspect.isasyncgen(response):
        async with aclosing(response):
            async for chunk in response:
                yield chunk
    else:
        yield response
