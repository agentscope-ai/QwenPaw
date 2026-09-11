# -*- coding: utf-8 -*-
"""Resource limits for streaming requests to personal runtimes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress

import httpx


class ProxyRequestTooLargeError(RuntimeError):
    """Raised when a proxied request exceeds its configured size limit."""


class ProxyRequestIdleTimeoutError(RuntimeError):
    """Raised when a proxied request body stops producing data."""


async def limited_request_stream(
    stream: AsyncIterable[bytes],
    *,
    max_bytes: int,
    idle_timeout_seconds: float,
    completion_event: asyncio.Event,
) -> AsyncIterator[bytes]:
    """Yield a request body while bounding its size and idle duration."""
    iterator = aiter(stream)
    total = 0
    while True:
        try:
            async with asyncio.timeout(idle_timeout_seconds):
                chunk = await anext(iterator)
        except StopAsyncIteration:
            completion_event.set()
            return
        except TimeoutError as exc:
            raise ProxyRequestIdleTimeoutError(
                "Personal runtime request body timed out",
            ) from exc
        total += len(chunk)
        if total > max_bytes:
            raise ProxyRequestTooLargeError(
                "Personal runtime request body is too large",
            )
        yield chunk


async def send_with_response_header_timeout(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    request_complete: asyncio.Event,
    timeout_seconds: float,
) -> httpx.Response:
    """Wait for response headers without timing the request upload itself."""
    send_task = asyncio.create_task(client.send(request, stream=True))
    request_complete_task = asyncio.create_task(request_complete.wait())
    try:
        done, _ = await asyncio.wait(
            {send_task, request_complete_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if send_task in done:
            return send_task.result()
        async with asyncio.timeout(timeout_seconds):
            return await send_task
    finally:
        request_complete_task.cancel()
        with suppress(asyncio.CancelledError):
            await request_complete_task
        if not send_task.done():
            send_task.cancel()
            with suppress(asyncio.CancelledError):
                await send_task
