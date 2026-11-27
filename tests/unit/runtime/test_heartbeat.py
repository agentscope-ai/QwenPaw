# -*- coding: utf-8 -*-
"""Tests for the runtime heartbeat iterator wrapper."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from qwenpaw.runtime.executor import AgentExecutor
from qwenpaw.runtime.steer import SteerOutput
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


@pytest.mark.asyncio
async def test_executor_close_releases_suspended_source_without_gc():
    closed = asyncio.Event()

    async def source():
        try:
            yield SteerOutput("boundary")
            pytest.fail("closing must not request another model step")
        finally:
            closed.set()

    # Keep a strong reference so garbage collection cannot close the source.
    raw = source()
    agent = SimpleNamespace(reply_stream=lambda **kwargs: raw)
    stream = AgentExecutor(agent, None).run([])
    try:
        assert await anext(stream) == "boundary"
        await stream.aclose()
        assert closed.is_set()
        assert raw.ag_frame is None
    finally:
        await raw.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["primary", "close"])
async def test_executor_cleanup_preserves_primary_failure(failure):
    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if failure == "close":
                return SteerOutput("boundary")
            return SimpleNamespace(type="test")

        async def aclose(self):
            raise RuntimeError("cleanup failure")

    async def translate(event):
        raise LookupError("primary failure")
        yield

    raw = Source()
    agent = SimpleNamespace(reply_stream=lambda **kwargs: raw)
    envelope = SimpleNamespace(translate_event=translate)
    stream = AgentExecutor(agent, envelope).run([])
    try:
        if failure == "close":
            assert await anext(stream) == "boundary"
            with pytest.raises(RuntimeError, match="cleanup failure"):
                await stream.aclose()
        else:
            with pytest.raises(LookupError, match="primary failure"):
                await anext(stream)
    finally:
        await stream.aclose()
