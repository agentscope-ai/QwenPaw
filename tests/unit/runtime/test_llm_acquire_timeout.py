# -*- coding: utf-8 -*-
"""LLM acquire timeout regression tests.

Regression for #5411: LLM acquire timeout must not leave the agent hung.

When ``LLMRateLimiter.acquire()`` times out (an internal acquire timeout,
distinct from an API 429), ``RetryChatModel.__call__`` must raise
``_AcquireTimeoutError`` immediately (no retry loop), release no semaphore
slot it never took, and leave no pending asyncio task behind. Before the
#5411 fix, a leaked semaphore slot from a prior cancelled stream could hang
the agent until the 300s default ``acquire_timeout`` elapsed.
"""

# pylint: disable=protected-access,too-few-public-methods

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, AsyncGenerator, cast
from unittest.mock import AsyncMock, patch

import pytest
from agentscope.model._model_response import ChatResponse

from qwenpaw.providers.rate_limiter import LLMRateLimiter
from qwenpaw.providers.retry_chat_model import (
    RateLimitConfig,
    RetryChatModel,
    RetryConfig,
    _AcquireTimeoutError,
)

_TEST_ACQUIRE_TIMEOUT = 0.01


class _HungInnerModel:
    """Stand-in inner model whose ``acquire`` hangs forever.

    The real blocking primitive is the rate-limiter semaphore; we mock the
    limiter itself, so the inner model never runs.
    """

    model = "acquire-timeout-test"
    stream = False
    context_size = 32768
    parameters = None
    _provider_id = "unit"
    credential = None

    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        # Should never be reached — acquire raises before the inner call.
        raise AssertionError("inner model __call__ should not be reached")


async def _successful_stream() -> AsyncGenerator[Any, None]:
    yield _OKResponse()


class _StreamingInnerModel:
    """Streaming model used to verify lazy semaphore ownership."""

    model = "acquire-timeout-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"
    credential = None

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        return _successful_stream()


class _BlockingStreamingInnerModel(_StreamingInnerModel):
    """Streaming model that never produces its first chunk.

    ``release`` intentionally remains unset.  Cancelling the consumer task
    must terminate the wait and close the stream.
    """

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def _blocking_stream(self) -> AsyncGenerator[Any, None]:
        self.started.set()
        await self.release.wait()
        yield _OKResponse()

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        return self._blocking_stream()


class _CompletedStreamingInnerModel(_StreamingInnerModel):
    """Streaming model that returns a completed response directly."""

    def __init__(self) -> None:
        super().__init__()
        self.response = ChatResponse(
            content=[],
            is_last=True,
        )

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> ChatResponse:
        self.calls += 1
        return self.response


def _build_model() -> RetryChatModel:
    return RetryChatModel(
        _HungInnerModel(),  # type: ignore[arg-type]
        retry_config=RetryConfig(enabled=True, max_retries=3),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            max_qpm=0,
            pause_seconds=1.0,
            jitter_range=0.0,
            acquire_timeout=10.0,
        ),
    )


def _build_streaming_model(
    inner: _StreamingInnerModel,
) -> RetryChatModel:
    return RetryChatModel(
        inner,
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            max_qpm=0,
            pause_seconds=1.0,
            jitter_range=0.0,
            acquire_timeout=10.0,
        ),
    )


def _use_fast_acquire_timeout(model: RetryChatModel) -> None:
    """Shorten real timeout-path tests without changing production bounds."""
    model._rate_limit_config = replace(
        model._rate_limit_config,
        acquire_timeout=_TEST_ACQUIRE_TIMEOUT,
    )


async def _consume_streaming_model(
    model: RetryChatModel,
) -> list[Any]:
    result = await model(messages=[])
    return [chunk async for chunk in cast(AsyncGenerator[Any, None], result)]


@pytest.mark.asyncio
async def test_unconsumed_stream_does_not_acquire_semaphore() -> None:
    """Returning or closing an unconsumed stream must not take a slot."""
    inner = _StreamingInnerModel()
    model = _build_streaming_model(inner)
    limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=1.0,
        jitter_range=0.0,
    )

    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=limiter,
    ):
        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)

        assert inner.calls == 0
        assert limiter.stats()["current_in_flight"] == 0

        await stream.aclose()

        assert limiter.stats()["current_in_flight"] == 0

        chunks = await asyncio.wait_for(
            _consume_streaming_model(model),
            timeout=0.1,
        )

    assert len(chunks) == 1
    assert inner.calls == 1
    assert limiter.stats()["current_in_flight"] == 0


@pytest.mark.asyncio
async def test_stream_cancelled_before_first_iteration_does_not_leak() -> None:
    """Cancellation before the lazy stream starts must leave no slot held."""
    inner = _StreamingInnerModel()
    model = _build_streaming_model(inner)
    limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=1.0,
        jitter_range=0.0,
    )

    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=limiter,
    ):
        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        pending = asyncio.ensure_future(stream.__anext__())
        pending.cancel()

        with pytest.raises(asyncio.CancelledError):
            await pending

        await stream.aclose()

    assert inner.calls == 0
    assert limiter.stats()["current_in_flight"] == 0


@pytest.mark.asyncio
async def test_stream_cancelled_before_first_chunk_releases() -> None:
    """Cancellation after acquire but before the first chunk releases once."""
    inner = _BlockingStreamingInnerModel()
    model = _build_streaming_model(inner)
    limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=1.0,
        jitter_range=0.0,
    )

    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=limiter,
    ):
        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        pending = asyncio.ensure_future(stream.__anext__())
        try:
            await asyncio.wait_for(inner.started.wait(), timeout=1.0)

            assert inner.calls == 1
            assert limiter.stats()["current_in_flight"] == 1
        finally:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await stream.aclose()

    assert limiter.stats()["current_in_flight"] == 0
    assert limiter.stats()["current_available"] == 1


@pytest.mark.asyncio
async def test_streaming_model_wraps_final_response() -> None:
    """A direct final response remains complete when exposed as a stream."""
    inner = _CompletedStreamingInnerModel()
    model = _build_streaming_model(inner)
    limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=1.0,
        jitter_range=0.0,
    )

    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=limiter,
    ):
        chunks = await _consume_streaming_model(model)

    assert chunks == [inner.response]
    assert chunks[0].is_last is True
    assert inner.calls == 1
    assert limiter.stats()["current_in_flight"] == 0


@pytest.mark.asyncio
async def test_acquire_timeout_raises_typed_error() -> None:
    """Regression for #5411: an internal acquire timeout raises
    ``_AcquireTimeoutError`` (a typed RateLimitExceededException), not a bare
    asyncio.TimeoutError — so the retry handler can identify it and avoid
    retrying."""
    model = _build_model()

    fake_limiter = AsyncMock()
    fake_limiter.acquire.side_effect = asyncio.TimeoutError()
    fake_limiter.release = AsyncMock()
    fake_limiter.on_success = AsyncMock()

    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=fake_limiter,
    ):
        with pytest.raises(_AcquireTimeoutError):
            await model(messages=[{"role": "user", "content": "hi"}])

    # The retry loop must NOT have retried on an internal acquire timeout.
    assert fake_limiter.acquire.await_count == 1


@pytest.mark.asyncio
async def test_acquire_timeout_does_not_release_semaphore() -> None:
    """Regression for #5411: when acquire times out, ``acquired`` is False so
    the finally block must not call ``release()`` — a spurious release would
    leak the semaphore above its max_concurrent cap."""
    model = _build_model()

    fake_limiter = AsyncMock()
    fake_limiter.acquire.side_effect = asyncio.TimeoutError()
    fake_limiter.release = AsyncMock()

    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=fake_limiter,
    ):
        with pytest.raises(_AcquireTimeoutError):
            await model(messages=[{"role": "user", "content": "hi"}])

    fake_limiter.release.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_timeout_leaves_no_pending_tasks() -> None:
    """Regression for #5411: after the timeout propagates, no lingering
    ``limiter.acquire()`` coroutine should remain pending — the agent must be
    fully released and ready for the next run."""
    model = _build_model()
    _use_fast_acquire_timeout(model)

    # A real limiter whose acquire sleeps longer than the timeout. This
    # exercises the real ``asyncio.wait_for`` cancellation path.
    real_limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=0.0,
        jitter_range=0.0,
    )

    async def _hang_forever() -> float:
        await asyncio.sleep(3600)
        return 0.0

    with patch.object(real_limiter, "acquire", side_effect=_hang_forever):
        with patch(
            "qwenpaw.providers.retry_chat_model.get_rate_limiter",
            return_value=real_limiter,
        ):
            with pytest.raises(_AcquireTimeoutError):
                await model(
                    messages=[{"role": "user", "content": "hi"}],
                )

    # Allow any cancellation cleanup to flush.
    await asyncio.sleep(0)

    # No pending tasks should reference the hung acquire coroutine.
    pending = asyncio.all_tasks()
    assert all("acquire" not in (t.get_name() or "") for t in pending)
    # The limiter slot was never taken, so in_flight stays at 0.
    assert real_limiter._in_flight == 0


@pytest.mark.asyncio
async def test_normal_call_after_timeout_succeeds() -> None:
    """Regression for #5411: after a prior acquire timeout, a subsequent call
    must not be hung by leaked limiter state — the agent is released and can
    serve again immediately."""
    model = _build_model()
    _use_fast_acquire_timeout(model)

    calls = {"n": 0}

    class _RecoveringInner:
        model = "acquire-timeout-test"
        stream = False
        context_size = 32768
        parameters = None
        _provider_id = "unit"
        credential = None

        async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
            calls["n"] += 1
            return _OKResponse()

    # Swap the inner model to a succeeding one for the second call.
    model2 = RetryChatModel(
        _RecoveringInner(),  # type: ignore[arg-type]
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            max_qpm=0,
            pause_seconds=1.0,
            jitter_range=0.0,
            acquire_timeout=10.0,
        ),
    )

    limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=0.0,
        jitter_range=0.0,
    )

    # First call: acquire times out.
    async def _hang() -> float:
        await asyncio.sleep(3600)
        return 0.0

    with patch.object(limiter, "acquire", side_effect=_hang):
        with patch(
            "qwenpaw.providers.retry_chat_model.get_rate_limiter",
            return_value=limiter,
        ):
            with pytest.raises(_AcquireTimeoutError):
                await model(messages=[{"role": "user", "content": "hi"}])

    # Second call: real acquire path, inner model succeeds.
    with patch(
        "qwenpaw.providers.retry_chat_model.get_rate_limiter",
        return_value=limiter,
    ):
        result = await model2(messages=[{"role": "user", "content": "hi"}])
        assert result is not None
        assert calls["n"] == 1

    # Limiter is fully released after the successful call.
    assert limiter._in_flight == 0
    assert limiter._semaphore._value == limiter._max_concurrent


class _OKResponse:
    """Minimal stand-in for a non-streaming ChatResponse."""

    def __init__(self) -> None:
        self.content = "ok"
