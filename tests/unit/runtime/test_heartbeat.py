# -*- coding: utf-8 -*-
"""Tests for the runtime heartbeat iterator wrapper."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from qwenpaw.runtime.heartbeat import (
    _iter_with_heartbeat,
    _HEARTBEAT_TICK,
)


class _SourceIdleTimeoutError(TimeoutError):
    """Represent a timeout raised by the wrapped source iterator."""


class _FailingSource(AsyncIterator[object]):
    """Raise a configured exception when the next item is requested."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __aiter__(self) -> _FailingSource:
        return self

    async def __anext__(self) -> object:
        raise self._error


@pytest.mark.asyncio
async def test_source_timeout_error_propagates() -> None:
    stream = _iter_with_heartbeat(
        _FailingSource(
            _SourceIdleTimeoutError("source stream idle"),
        ),
        interval=1.0,
    )

    try:
        with pytest.raises(
            _SourceIdleTimeoutError,
            match="source stream idle",
        ):
            await anext(stream)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_pending_source_emits_heartbeat_then_value() -> None:
    release = asyncio.Event()

    async def source() -> AsyncIterator[str]:
        await release.wait()
        yield "value"

    stream = _iter_with_heartbeat(source(), interval=0.01)

    try:
        assert await anext(stream) is _HEARTBEAT_TICK
        release.set()
        assert await anext(stream) == "value"
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_non_timeout_source_error_propagates() -> None:
    stream = _iter_with_heartbeat(
        _FailingSource(RuntimeError("source failed")),
        interval=1.0,
    )

    try:
        with pytest.raises(RuntimeError, match="source failed"):
            await anext(stream)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_closing_wrapper_cancels_pending_source() -> None:
    source_cancelled = asyncio.Event()
    wait_forever = asyncio.Event()

    async def source() -> AsyncIterator[object]:
        try:
            await wait_forever.wait()
            yield object()  # pragma: no cover
        finally:
            source_cancelled.set()

    stream = _iter_with_heartbeat(source(), interval=0.01)

    assert await anext(stream) is _HEARTBEAT_TICK
    await stream.aclose()
    await asyncio.sleep(0)

    assert source_cancelled.is_set()
