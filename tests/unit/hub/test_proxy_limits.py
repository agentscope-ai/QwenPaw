# -*- coding: utf-8 -*-
"""Tests for personal runtime proxy resource limits."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.hub.proxy_limits import (
    ProxyRequestIdleTimeoutError,
    ProxyRequestTooLargeError,
    limited_request_stream,
)


@pytest.mark.asyncio
async def test_streaming_request_enforces_accumulated_size() -> None:
    async def chunks():
        yield b"abc"
        yield b"def"

    completion = asyncio.Event()
    stream = limited_request_stream(
        chunks(),
        max_bytes=5,
        idle_timeout_seconds=1,
        completion_event=completion,
    )

    with pytest.raises(ProxyRequestTooLargeError):
        _ = [chunk async for chunk in stream]

    assert completion.is_set() is False


@pytest.mark.asyncio
async def test_streaming_request_enforces_idle_timeout() -> None:
    async def stalled_chunks():
        await asyncio.sleep(1)
        yield b"late"

    completion = asyncio.Event()
    stream = limited_request_stream(
        stalled_chunks(),
        max_bytes=1024,
        idle_timeout_seconds=0.01,
        completion_event=completion,
    )

    with pytest.raises(ProxyRequestIdleTimeoutError):
        _ = [chunk async for chunk in stream]

    assert completion.is_set() is False
