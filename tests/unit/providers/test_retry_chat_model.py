# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-few-public-methods
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncGenerator, cast

import pytest
from agentscope.agent import Agent, InjectionConfig
from agentscope.message import (
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
)
from agentscope.model._model_response import ChatResponse
from agentscope.tool import Toolkit

from qwenpaw.agents import model_factory
from qwenpaw.providers.capping_formatter import _CappingOpenAIFormatter
from qwenpaw.providers.model_capability_cache import get_capability_cache
from qwenpaw.providers.model_error_policy import RETRYABLE_STATUS_CODES
from qwenpaw.providers.rate_limiter import LLMRateLimiter, _limiters
from qwenpaw.providers.retry_chat_model import (
    RetryChatModel,
    RetryConfig,
    RateLimitConfig,
    StreamCleanupPendingError,
    StreamIdleTimeoutError,
    _compute_backoff,
    _enable_reasoning_content_fallback,
    _extract_retry_after,
    _extract_status_code,
    _inject_reasoning_content,
    _is_missing_reasoning_content_error,
    _is_rate_limit,
    _is_retryable,
    _normalize_rate_limit_config,
    _normalize_retry_config,
)
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


async def _failing_reasoning_stream() -> AsyncGenerator[Any, None]:
    for chunk in ():
        yield chunk
    exc = Exception("The `reasoning_content` in thinking mode is required")
    exc.status_code = 400  # type: ignore[attr-defined]
    raise exc


async def _successful_stream() -> AsyncGenerator[Any, None]:
    yield SimpleNamespace(content="ok")


async def _empty_then_failing_stream() -> AsyncGenerator[Any, None]:
    yield SimpleNamespace(content=[])
    status_code = 503
    exc = Exception(f"temporary failure: {status_code}")
    exc.status_code = 503  # type: ignore[attr-defined]
    raise exc


async def _hanging_stream(
    state: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    state["started"].set()
    try:
        await asyncio.Event().wait()
        yield SimpleNamespace(content="unreachable")
    finally:
        state["closed"] = True


async def _partial_then_hanging_stream(
    state: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    try:
        yield SimpleNamespace(content="partial")
        state["started"].set()
        await asyncio.Event().wait()
    finally:
        state["closed"] = True


async def _delayed_first_then_hanging_stream(
    state: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    try:
        await asyncio.sleep(0.2)
        yield SimpleNamespace(content="first")
        state["started"].set()
        await asyncio.Event().wait()
    finally:
        state["closed"] = True


async def _empty_heartbeat_stream(
    state: dict[str, Any],
) -> AsyncGenerator[Any, None]:
    state["started"].set()
    try:
        while True:
            yield SimpleNamespace(content=[])
            await asyncio.sleep(0.01)
    finally:
        state["closed"] = True


async def _slow_thinking_stream() -> AsyncGenerator[ChatResponse, None]:
    for index in range(6):
        await asyncio.sleep(0.04)
        yield ChatResponse(
            content=[ThinkingBlock(thinking=f"step-{index}")],
            is_last=False,
        )


async def _immediate_content_stream() -> AsyncGenerator[Any, None]:
    yield SimpleNamespace(content="first")
    yield SimpleNamespace(content="second")


async def _final_then_hanging_stream(
    state: dict[str, bool],
) -> AsyncGenerator[ChatResponse, None]:
    try:
        state["yielded"] = True
        yield ChatResponse(
            content=[TextBlock(text="complete")],
            is_last=True,
        )
        state["continued_after_final"] = True
        await asyncio.Event().wait()
    finally:
        state["closed"] = True


class _SlowCloseStream:
    """Stream whose close operation completes only after release."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = asyncio.Event()
        self.cancelled = False

    async def aclose(self) -> None:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.completed.set()


class _NonCooperativeStreamModel:
    """Model whose streams wait for explicit release after cancellation."""

    model = "non-cooperative-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.release = asyncio.Event()
        self.closed = asyncio.Event()

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        return self._stream()

    async def _stream(self) -> AsyncGenerator[Any, None]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await self.release.wait()
                raise
            yield SimpleNamespace(content="unreachable")
        finally:
            self.active -= 1
            self.closed.set()


class _IdleStreamModel:
    model = "idle-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self, streams: list[AsyncGenerator[Any, None]]) -> None:
        self.streams = streams
        self.calls = 0

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        stream = self.streams[self.calls]
        self.calls += 1
        return stream


async def test_wrapped_model_exposes_formatter_and_model_name() -> None:
    """AgentScope attributes stay visible through both QwenPaw wrappers."""
    formatter = SimpleNamespace(supported_input_media_types=[])
    provider_model = SimpleNamespace(
        credential=None,
        model="wrapped-model",
        parameters=None,
        stream=True,
        context_size=32768,
        formatter=formatter,
    )
    recording_model = TokenRecordingModelWrapper(
        provider_id="unit",
        model=provider_model,  # type: ignore[arg-type]
    )
    retry_model = RetryChatModel(
        recording_model,
        retry_config=RetryConfig(enabled=False),
    )

    assert retry_model.model == "wrapped-model"
    assert retry_model.formatter is formatter
    assert retry_model.formatter.supported_input_media_types == []

    replacement = SimpleNamespace(supported_input_media_types=["image/*"])
    retry_model.formatter = replacement

    assert recording_model.formatter is replacement
    assert provider_model.formatter is replacement

    agent = Agent(
        name="test-agent",
        system_prompt="",
        model=retry_model,
        toolkit=Toolkit(tools=[]),
        injection_config=InjectionConfig(inject_runtime_state=False),
    )
    await agent._handle_incoming_messages(  # pylint: disable=protected-access
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="hello")],
        ),
    )

    assert agent.state.context[-1].get_text_content() == "hello"


class _ReasoningRetryStreamModel:
    model = "reasoning-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        if self.calls == 1:
            return _failing_reasoning_stream()
        return _successful_stream()


class _ReasoningRetryMsgStreamModel:
    model = "reasoning-msg-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self) -> None:
        formatter_class = model_factory._create_file_block_support_formatter(
            _CappingOpenAIFormatter,
        )
        self.formatter = formatter_class(relay_reasoning_content=True)
        self.calls = 0
        self.formatted_calls: list[list[dict[str, Any]]] = []

    async def __call__(
        self,
        messages: list[Msg],
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        formatted = await self.formatter.format(messages)
        self.formatted_calls.append(formatted)
        assistants = [
            message
            for message in formatted
            if message.get("role") == "assistant"
        ]
        if any("reasoning_content" not in message for message in assistants):
            return _failing_reasoning_stream()
        return _successful_stream()


# ---------------------------------------------------------------------------
# Wrapper contract
# ---------------------------------------------------------------------------


def test_retry_wrapper_exposes_inner_formatter() -> None:
    """AgentScope can inspect media support on the outermost model."""
    inner = _ReasoningRetryMsgStreamModel()
    model = RetryChatModel(inner)  # type: ignore[arg-type]

    assert model.formatter is inner.formatter


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(RETRYABLE_STATUS_CODES))
def test_is_retryable_status_codes(code: int) -> None:
    exc = Exception()
    exc.status_code = code  # type: ignore[attr-defined]
    assert _is_retryable(exc) is True


def test_is_retryable_non_retryable_code() -> None:
    exc = Exception()
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _is_retryable(exc) is False


def test_is_retryable_no_status_code() -> None:
    assert _is_retryable(Exception("plain")) is False


def test_extract_status_code_from_body_top_level() -> None:
    exc = Exception()
    exc.body = {"status_code": 502}  # type: ignore[attr-defined]
    assert _extract_status_code(exc) == 502


def test_extract_status_code_from_body_error_object() -> None:
    exc = Exception()
    exc.body = {  # type: ignore[attr-defined]
        "error": {
            "message": "Internal error: ReadError",
            "code": 500,
            "status_code": 500,
        },
        "status_code": 500,
    }
    assert _extract_status_code(exc) == 500


def test_is_retryable_streaming_openai_api_error_with_body_status() -> None:
    openai = pytest.importorskip("openai")

    body = {
        "error": {
            "message": "Internal error: ReadError",
            "type": "internal_error",
            "code": 500,
            "status_code": 500,
        },
        "status_code": 500,
    }
    exc = openai.APIError(
        "API错误(502): Internal error: ReadError",
        request=None,
        body=body,
    )
    assert _is_retryable(exc) is True


def test_is_retryable_streaming_openai_api_error_504_timeout() -> None:
    openai = pytest.importorskip("openai")

    body = {
        "error": {
            "message": "Request timeout: WriteTimeout",
            "type": "timeout_error",
            "code": 504,
            "request_id": "1408263304014e1c90a09e1990d79c0a",
        },
        "status_code": 504,
    }
    exc = openai.APIError(
        'API错误(504): {"error": {...}, "status_code": 504}',
        request=None,
        body=body,
    )
    assert _extract_status_code(exc) == 504
    assert _is_retryable(exc) is True


def test_is_retryable_openai_internal_server_error() -> None:
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    internal_server_error = getattr(openai, "InternalServerError", None)
    if internal_server_error is None:
        pytest.skip("openai.InternalServerError unavailable")
    assert internal_server_error is not None

    response = httpx.Response(
        502,
        request=httpx.Request("POST", "http://example.com/v1/chat"),
    )
    exc = internal_server_error(
        "bad gateway",
        response=response,
        body=None,
    )
    assert _is_retryable(exc) is True


async def _failing_stream_api_error(
    content: Any,
) -> AsyncGenerator[Any, None]:
    openai = pytest.importorskip("openai")
    yield SimpleNamespace(content=content)
    body = {
        "error": {
            "message": "Internal error: ReadError",
            "code": 500,
            "status_code": 500,
        },
        "status_code": 500,
    }
    raise openai.APIError(
        "API错误(502): Internal error: ReadError",
        request=None,
        body=body,
    )


class _TransientStreamRetryModel:
    model = "transient-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self, content: Any) -> None:
        self.calls = 0
        self.content = content

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        if self.calls == 1:
            return _failing_stream_api_error(self.content)
        return _successful_stream()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text", "text": "partial"}],
        [{"type": "thinking", "thinking": "partial"}],
        [{"type": "tool_use", "id": "call-1", "name": "tool"}],
        [{"type": "data", "data": "media"}],
    ],
)
async def test_stream_does_not_retry_after_visible_output(
    content: Any,
) -> None:
    openai = pytest.importorskip("openai")
    _limiters.clear()
    try:
        inner = _TransientStreamRetryModel(content)
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=2,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )

        result = await model(messages=[{"role": "user", "content": "hi"}])
        stream = cast(AsyncGenerator[Any, None], result)
        with pytest.raises(openai.APIError):
            _ = [chunk async for chunk in stream]

        assert inner.calls == 1
    finally:
        _limiters.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        [TextBlock(text="")],
        [ThinkingBlock(thinking="")],
        [ToolCallBlock(id="call-1", name="", input="")],
    ],
)
async def test_stream_retries_after_empty_payload_block(
    content: Any,
) -> None:
    pytest.importorskip("openai")
    _limiters.clear()
    try:
        inner = _TransientStreamRetryModel(content)
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=1,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content for chunk in chunks] == [content, "ok"]
        assert inner.calls == 2
    finally:
        _limiters.clear()


class _EmptyControlRetryModel:
    model = "empty-control-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        if self.calls == 1:
            return _empty_then_failing_stream()
        return _successful_stream()


@pytest.mark.asyncio
async def test_stream_retries_after_empty_control_chunk() -> None:
    _limiters.clear()
    try:
        inner = _EmptyControlRetryModel()
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=2,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content for chunk in chunks] == [[], "ok"]
        assert inner.calls == 2
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_stream_idle_timeout_retries_before_visible_output() -> None:
    _limiters.clear()
    state = {
        "started": asyncio.Event(),
        "closed": False,
    }
    try:
        inner = _IdleStreamModel(
            [
                _hanging_stream(state),
                _successful_stream(),
            ],
        )
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=1,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_first_content_timeout=0.15,
            stream_idle_timeout=0.15,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content for chunk in chunks] == ["ok"]
        assert inner.calls == 2
        assert state["started"].is_set() is True
        assert state["closed"] is True
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_stream_idle_timeout_does_not_retry_after_output() -> None:
    _limiters.clear()
    state = {
        "started": asyncio.Event(),
        "closed": False,
    }
    try:
        inner = _IdleStreamModel(
            [_partial_then_hanging_stream(state)],
        )
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=2,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_idle_timeout=0.15,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        contents = []
        with pytest.raises(StreamIdleTimeoutError) as exc_info:
            async for chunk in stream:
                contents.append(chunk.content)

        assert contents == ["partial"]
        assert inner.calls == 1
        assert state["started"].is_set() is True
        assert state["closed"] is True
        assert exc_info.value.model_key == "unit:idle-stream-test"
        assert exc_info.value.timeout_seconds == 0.15
        assert str(exc_info.value) == (
            "LLM stream for unit:idle-stream-test produced no content for "
            "0.15s. Set QWENPAW_LLM_STREAM_IDLE_TIMEOUT to adjust this "
            "timeout"
        )
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_final_chunk_ends_stream_without_idle_timeout() -> None:
    _limiters.clear()
    state = {
        "yielded": False,
        "continued_after_final": False,
        "closed": False,
    }
    try:
        inner = _IdleStreamModel([_final_then_hanging_stream(state)])
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_idle_timeout=0.05,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert len(chunks) == 1
        assert chunks[0].is_last is True
        assert [(type(block), block.text) for block in chunks[0].content] == [
            (TextBlock, "complete"),
        ]
        assert state == {
            "yielded": True,
            "continued_after_final": False,
            "closed": True,
        }
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_slow_stream_close_continues_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.providers.retry_chat_model._STREAM_CLEANUP_TIMEOUT",
        0.02,
    )
    model = RetryChatModel(
        _IdleStreamModel([]),  # type: ignore[arg-type]
        retry_config=RetryConfig(enabled=False),
    )
    provider_stream = _SlowCloseStream()

    await model._close_stream_bounded(  # pylint: disable=protected-access
        provider_stream,  # type: ignore[arg-type]
    )

    assert provider_stream.started.is_set() is True
    assert provider_stream.cancelled is False
    assert provider_stream.completed.is_set() is False
    assert len(model._pending_provider_cleanup_tasks) == 1

    provider_stream.release.set()
    await asyncio.wait_for(provider_stream.completed.wait(), timeout=1.0)
    await asyncio.sleep(0)

    assert provider_stream.cancelled is False
    assert provider_stream.completed.is_set() is True
    assert model._pending_provider_cleanup_tasks == set()


@pytest.mark.asyncio
async def test_deferred_cleanup_quarantines_model_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.providers.retry_chat_model._STREAM_CLEANUP_TIMEOUT",
        0.02,
    )
    _limiters.clear()
    inner = _NonCooperativeStreamModel()
    model = RetryChatModel(
        inner,  # type: ignore[arg-type]
        retry_config=RetryConfig(
            enabled=True,
            max_retries=2,
            backoff_base=0.01,
            backoff_cap=0.01,
        ),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            max_qpm=0,
            pause_seconds=1.0,
            jitter_range=0.0,
            acquire_timeout=10.0,
        ),
        stream_first_content_timeout=0.05,
    )
    try:
        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        with pytest.raises(StreamIdleTimeoutError) as exc_info:
            await anext(stream)

        assert exc_info.value.cleanup_deferred is True
        assert {
            "calls": inner.calls,
            "active": inner.active,
            "max_active": inner.max_active,
            "limiter_in_flight": _limiters[model.model_key].stats()[
                "current_in_flight"
            ],
            "pending_cleanup": len(model._pending_provider_cleanup_tasks),
        } == {
            "calls": 1,
            "active": 1,
            "max_active": 1,
            "limiter_in_flight": 0,
            "pending_cleanup": 1,
        }

        with pytest.raises(StreamCleanupPendingError):
            await model(messages=[])

        peer = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
        )
        with pytest.raises(StreamCleanupPendingError):
            await peer(messages=[])
        assert inner.calls == 1
    finally:
        inner.release.set()
        if inner.active:
            await asyncio.wait_for(inner.closed.wait(), timeout=1.0)
        for _ in range(10):
            if not model._pending_provider_cleanup_tasks:
                break
            await asyncio.sleep(0.01)
        _limiters.clear()

    assert inner.active == 0
    assert model._pending_provider_cleanup_tasks == set()


@pytest.mark.asyncio
async def test_first_content_uses_longer_timeout_than_later_chunks() -> None:
    _limiters.clear()
    state = {
        "started": asyncio.Event(),
        "closed": False,
    }
    try:
        inner = _IdleStreamModel(
            [_delayed_first_then_hanging_stream(state)],
        )
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_first_content_timeout=2.0,
            stream_idle_timeout=0.15,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        contents = []
        with pytest.raises(StreamIdleTimeoutError) as exc_info:
            async for chunk in stream:
                contents.append(chunk.content)

        assert contents == ["first"]
        assert exc_info.value.timeout_seconds == 0.15
        assert state["started"].is_set() is True
        assert state["closed"] is True
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_empty_chunks_do_not_reset_stream_idle_timeout() -> None:
    _limiters.clear()
    state = {
        "started": asyncio.Event(),
        "closed": False,
    }
    try:
        inner = _IdleStreamModel([_empty_heartbeat_stream(state)])
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_first_content_timeout=0.15,
            stream_idle_timeout=5.0,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        contents = []
        with pytest.raises(StreamIdleTimeoutError) as exc_info:
            async for chunk in stream:
                contents.append(chunk.content)

        assert contents
        assert all(content == [] for content in contents)
        assert exc_info.value.timeout_seconds == 0.15
        assert "QWENPAW_LLM_STREAM_FIRST_CONTENT_TIMEOUT" in str(
            exc_info.value,
        )
        assert state["started"].is_set() is True
        assert state["closed"] is True
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_thinking_chunks_reset_stream_idle_timeout() -> None:
    _limiters.clear()
    try:
        inner = _IdleStreamModel([_slow_thinking_stream()])
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_idle_timeout=0.2,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content[0].thinking for chunk in chunks] == [
            "step-0",
            "step-1",
            "step-2",
            "step-3",
            "step-4",
            "step-5",
        ]
        assert inner.calls == 1
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_consumer_backpressure_does_not_consume_idle_budget() -> None:
    _limiters.clear()
    try:
        inner = _IdleStreamModel([_immediate_content_stream()])
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_idle_timeout=0.1,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        first = await anext(stream)
        await asyncio.sleep(0.2)
        second = await anext(stream)

        assert [first.content, second.content] == ["first", "second"]
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_zero_stream_timeouts_disable_watchdog() -> None:
    _limiters.clear()
    state = {
        "started": asyncio.Event(),
        "closed": False,
    }
    try:
        inner = _IdleStreamModel([_hanging_stream(state)])
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_first_content_timeout=0,
            stream_idle_timeout=0,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        consume_task = asyncio.ensure_future(anext(stream))
        await state["started"].wait()
        await asyncio.sleep(0.2)

        assert consume_task.done() is False
        consume_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consume_task
        assert state["closed"] is True
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_stream_cancellation_is_not_reported_as_idle_timeout() -> None:
    _limiters.clear()
    state = {
        "started": asyncio.Event(),
        "closed": False,
    }
    try:
        inner = _IdleStreamModel([_hanging_stream(state)])
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
            stream_first_content_timeout=5.0,
            stream_idle_timeout=5.0,
        )

        result = await model(messages=[])
        stream = cast(AsyncGenerator[Any, None], result)
        consume_task = asyncio.ensure_future(anext(stream))
        await state["started"].wait()
        consume_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await consume_task

        await stream.aclose()
        assert state["closed"] is True
        assert _limiters[model.model_key].stats()["current_in_flight"] == 0
    finally:
        _limiters.clear()


class _StructuredRetryModel:
    model = "structured-retry-test"
    stream = False
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured_output(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> Any:
        self.calls += 1
        if self.calls == 1:
            status_code = 503
            exc = Exception(f"temporary failure: {status_code}")
            exc.status_code = 503  # type: ignore[attr-defined]
            raise exc
        return SimpleNamespace(value=f"ok-{self.calls}")


class _ResponseOnlyRateLimitModel:
    model = "response-only-rate-limit-test"
    stream = False
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured_output(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> Any:
        self.calls += 1
        if self.calls == 1:
            exc = Exception("Too many requests")
            exc.response = SimpleNamespace(  # type: ignore[attr-defined]
                status_code=429,
            )
            raise exc
        return SimpleNamespace(value=f"ok-{self.calls}")


@pytest.mark.asyncio
async def test_structured_output_retries_same_model() -> None:
    _limiters.clear()
    try:
        inner = _StructuredRetryModel()
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=2,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )

        result = await model.generate_structured_output(messages=[])

        assert result.value == "ok-2"
        assert inner.calls == 2
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_response_only_429_reports_rate_limit_and_retries(
    monkeypatch,
) -> None:
    reported: list[float | None] = []

    async def report_rate_limit(
        _limiter: LLMRateLimiter,
        retry_after: float | None = None,
    ) -> None:
        reported.append(retry_after)

    monkeypatch.setattr(
        LLMRateLimiter,
        "report_rate_limit",
        report_rate_limit,
    )
    _limiters.clear()
    try:
        inner = _ResponseOnlyRateLimitModel()
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(
                enabled=True,
                max_retries=1,
                backoff_base=0.01,
                backoff_cap=0.01,
            ),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )

        result = await model.generate_structured_output(messages=[])

        assert result.value == "ok-2"
        assert inner.calls == 2
        assert reported == [None]
    finally:
        _limiters.clear()


# ---------------------------------------------------------------------------
# _is_rate_limit
# ---------------------------------------------------------------------------


def test_is_rate_limit_429() -> None:
    exc = Exception()
    exc.status_code = 429  # type: ignore[attr-defined]
    assert _is_rate_limit(exc) is True


def test_is_rate_limit_500() -> None:
    exc = Exception()
    exc.status_code = 500  # type: ignore[attr-defined]
    assert _is_rate_limit(exc) is False


def test_is_rate_limit_no_attr() -> None:
    assert _is_rate_limit(Exception()) is False


# ---------------------------------------------------------------------------
# _is_missing_reasoning_content_error
# ---------------------------------------------------------------------------


def test_missing_reasoning_content_400() -> None:
    exc = Exception("reasoning_content is required")
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _is_missing_reasoning_content_error(exc) is True


def test_missing_reasoning_content_wrong_status() -> None:
    exc = Exception("reasoning_content is required")
    exc.status_code = 500  # type: ignore[attr-defined]
    assert _is_missing_reasoning_content_error(exc) is False


def test_missing_reasoning_content_wrong_message() -> None:
    exc = Exception("some other error")
    exc.status_code = 400  # type: ignore[attr-defined]
    assert _is_missing_reasoning_content_error(exc) is False


# ---------------------------------------------------------------------------
# _inject_reasoning_content
# ---------------------------------------------------------------------------


def test_inject_reasoning_content_via_kwargs() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
    ]
    result = _inject_reasoning_content((), {"messages": messages})
    assert result is True
    assert messages[1]["reasoning_content"] == " "
    assert "reasoning_content" not in messages[0]
    assert "reasoning_content" not in messages[2]


def test_inject_reasoning_content_via_args() -> None:
    messages = [{"role": "assistant", "content": "x"}]
    result = _inject_reasoning_content((messages,), {})
    assert result is True
    assert messages[0]["reasoning_content"] == " "


def test_inject_reasoning_content_already_present() -> None:
    messages = [
        {"role": "assistant", "content": "x", "reasoning_content": "think"},
    ]
    result = _inject_reasoning_content((), {"messages": messages})
    assert result is False
    assert messages[0]["reasoning_content"] == "think"


def test_inject_reasoning_content_no_messages() -> None:
    assert _inject_reasoning_content((), {}) is False


def test_inject_reasoning_content_empty_list() -> None:
    assert _inject_reasoning_content((), {"messages": []}) is False


def test_enable_reasoning_fallback_for_agentscope_messages() -> None:
    formatter = SimpleNamespace(
        _qwenpaw_supports_reasoning_content_fallback=True,
        _qwenpaw_require_reasoning_content=False,
    )
    provider_model = SimpleNamespace(formatter=formatter)
    token_wrapper = SimpleNamespace(_model=provider_model)
    retry_wrapper = SimpleNamespace(_inner=token_wrapper)
    messages = [
        Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(text="previous reply")],
        ),
    ]

    result = _enable_reasoning_content_fallback(
        retry_wrapper,
        (),
        {"messages": messages},
    )

    assert result is True
    assert formatter._qwenpaw_require_reasoning_content is True
    assert len(messages[0].content) == 1
    assert isinstance(messages[0].content[0], TextBlock)
    assert messages[0].content[0].text == "previous reply"


def test_enabled_reasoning_fallback_allows_concurrent_retry() -> None:
    formatter = SimpleNamespace(
        _qwenpaw_supports_reasoning_content_fallback=True,
        _qwenpaw_require_reasoning_content=True,
    )
    model = SimpleNamespace(formatter=formatter)
    messages = [
        Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(text="previous reply")],
        ),
    ]

    # Another request may have enabled the shared formatter after this one
    # was formatted.  This request must still be allowed to retry once.
    assert _enable_reasoning_content_fallback(
        model,
        (),
        {"messages": messages},
    )
    assert formatter._qwenpaw_require_reasoning_content is True


def test_reasoning_fallback_rejects_unsupported_formatter() -> None:
    formatter = SimpleNamespace()
    model = SimpleNamespace(formatter=formatter)
    messages = [
        Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(text="previous reply")],
        ),
    ]

    assert not _enable_reasoning_content_fallback(
        model,
        (),
        {"messages": messages},
    )


# ---------------------------------------------------------------------------
# _extract_retry_after
# ---------------------------------------------------------------------------


def test_extract_retry_after_from_headers() -> None:
    exc = Exception()
    exc.headers = {"Retry-After": "5.0"}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) == 5.0


def test_extract_retry_after_lowercase() -> None:
    exc = Exception()
    exc.headers = {"retry-after": "3"}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) == 3.0


def test_extract_retry_after_from_response() -> None:
    exc = Exception()
    exc.response = SimpleNamespace(  # type: ignore[attr-defined]
        headers={"Retry-After": "10"},
    )
    assert _extract_retry_after(exc) == 10.0


def test_extract_retry_after_no_header() -> None:
    exc = Exception()
    exc.headers = {}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) is None


def test_extract_retry_after_no_attrs() -> None:
    assert _extract_retry_after(Exception()) is None


def test_extract_retry_after_non_numeric() -> None:
    exc = Exception()
    exc.headers = {"Retry-After": "not-a-number"}  # type: ignore[attr-defined]
    assert _extract_retry_after(exc) is None


# ---------------------------------------------------------------------------
# _compute_backoff
# ---------------------------------------------------------------------------


def test_compute_backoff_first_attempt() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=60.0)
    assert _compute_backoff(1, cfg) == 2.0


def test_compute_backoff_second_attempt() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=60.0)
    assert _compute_backoff(2, cfg) == 4.0


def test_compute_backoff_third_attempt() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=60.0)
    assert _compute_backoff(3, cfg) == 8.0


def test_compute_backoff_capped() -> None:
    cfg = RetryConfig(backoff_base=2.0, backoff_cap=5.0)
    assert _compute_backoff(10, cfg) == 5.0


def test_compute_backoff_zero_attempt() -> None:
    cfg = RetryConfig(backoff_base=3.0, backoff_cap=60.0)
    assert _compute_backoff(0, cfg) == 3.0


# ---------------------------------------------------------------------------
# _normalize_retry_config
# ---------------------------------------------------------------------------


def test_normalize_retry_config_none_returns_default() -> None:
    result = _normalize_retry_config(None)
    assert isinstance(result, RetryConfig)


def test_normalize_retry_config_clamps_backoff_base() -> None:
    cfg = RetryConfig(backoff_base=0.01, backoff_cap=60.0)
    result = _normalize_retry_config(cfg)
    assert result.backoff_base == 0.1


def test_normalize_retry_config_cap_at_least_base() -> None:
    cfg = RetryConfig(backoff_base=10.0, backoff_cap=1.0)
    result = _normalize_retry_config(cfg)
    assert result.backoff_cap >= result.backoff_base


def test_normalize_retry_config_min_retries() -> None:
    cfg = RetryConfig(max_retries=0)
    result = _normalize_retry_config(cfg)
    assert result.max_retries >= 1


# ---------------------------------------------------------------------------
# _normalize_rate_limit_config
# ---------------------------------------------------------------------------


def test_normalize_rate_limit_config_none_returns_default() -> None:
    result = _normalize_rate_limit_config(None)
    assert isinstance(result, RateLimitConfig)


def test_normalize_rate_limit_config_clamps() -> None:
    cfg = RateLimitConfig(
        max_concurrent=0,
        max_qpm=-1,
        pause_seconds=0.1,
        jitter_range=-1.0,
        acquire_timeout=1.0,
    )
    result = _normalize_rate_limit_config(cfg)
    assert result.max_concurrent >= 1
    assert result.max_qpm >= 0
    assert result.pause_seconds >= 1.0
    assert result.jitter_range >= 0.0
    assert result.acquire_timeout >= 10.0


# ---------------------------------------------------------------------------
# RetryChatModel streaming reasoning_content recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_recovers_missing_reasoning_content_error() -> None:
    cache = get_capability_cache()
    model_key = "unit:reasoning-stream-test"
    cache.clear(model_key)

    try:
        inner = _ReasoningRetryStreamModel()
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )
        messages = [{"role": "assistant", "content": "previous reply"}]

        result = await model(messages=messages)
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content for chunk in chunks] == ["ok"]
        assert inner.calls == 2
        assert messages[0]["reasoning_content"] == " "
        assert cache.get(model_key, "needs_reasoning_content") is True
    finally:
        cache.clear(model_key)


@pytest.mark.asyncio
async def test_stream_recovers_agentscope_msg_via_formatter_fallback() -> None:
    cache = get_capability_cache()
    model_key = "unit:reasoning-msg-stream-test"
    cache.clear(model_key)

    try:
        inner = _ReasoningRetryMsgStreamModel()
        model = RetryChatModel(
            inner,  # type: ignore[arg-type]
            retry_config=RetryConfig(enabled=False),
            rate_limit_config=RateLimitConfig(
                max_concurrent=1,
                max_qpm=0,
                pause_seconds=1.0,
                jitter_range=0.0,
                acquire_timeout=10.0,
            ),
        )
        messages = [
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    ThinkingBlock(thinking="real tool reasoning"),
                    ToolCallBlock(id="call_1", name="tool", input="{}"),
                    ToolResultBlock(
                        id="call_1",
                        name="tool",
                        output=[TextBlock(text="result")],
                        state=ToolResultState.SUCCESS,
                    ),
                    TextBlock(text="done"),
                ],
            ),
        ]

        result = await model(messages=messages)
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content for chunk in chunks] == ["ok"]
        assert inner.calls == 2
        first_assistants = [
            message
            for message in inner.formatted_calls[0]
            if message.get("role") == "assistant"
        ]
        second_assistants = [
            message
            for message in inner.formatted_calls[1]
            if message.get("role") == "assistant"
        ]
        assert [
            message.get("reasoning_content") for message in first_assistants
        ] == ["real tool reasoning", None]
        assert [
            message.get("reasoning_content") for message in second_assistants
        ] == ["real tool reasoning", " "]
        assert inner.formatter._qwenpaw_require_reasoning_content is True
        assert cache.get(model_key, "needs_reasoning_content") is True
        assert [block.type for block in messages[0].content] == [
            "thinking",
            "tool_call",
            "tool_result",
            "text",
        ]
    finally:
        cache.clear(model_key)


# ---------------------------------------------------------------------------
# Streaming rate-limit policy
# ---------------------------------------------------------------------------


async def _failing_stream_rate_limit(
    retry_after: str,
) -> AsyncGenerator[Any, None]:
    for chunk in ():
        yield chunk
    exc = Exception("FreeUsageLimitError: daily quota exhausted")
    exc.status_code = 429  # type: ignore[attr-defined]
    exc.headers = {"Retry-After": retry_after}  # type: ignore[attr-defined]
    raise exc


class _RateLimitStreamModel:
    model = "rate-limit-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self, retry_after: str) -> None:
        self.calls = 0
        self.retry_after = retry_after

    async def __call__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        self.calls += 1
        if self.calls == 1:
            return _failing_stream_rate_limit(self.retry_after)
        return _successful_stream()


def _build_rate_limit_model(inner: _RateLimitStreamModel) -> RetryChatModel:
    return RetryChatModel(
        inner,  # type: ignore[arg-type]
        retry_config=RetryConfig(
            enabled=True,
            max_retries=2,
            backoff_base=0.01,
            backoff_cap=0.01,
        ),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            max_qpm=0,
            pause_seconds=1.0,
            jitter_range=0.0,
            acquire_timeout=10.0,
        ),
    )


@pytest.mark.asyncio
async def test_stream_rate_limit_over_cap_raises_without_pause() -> None:
    """A Retry-After above the cap must not be retried or reported."""
    _limiters.clear()
    try:
        inner = _RateLimitStreamModel("51496")
        model = _build_rate_limit_model(inner)

        result = await model(messages=[{"role": "user", "content": "hi"}])
        stream = cast(AsyncGenerator[Any, None], result)
        with pytest.raises(Exception, match="FreeUsageLimitError"):
            async for _chunk in stream:
                pass

        assert inner.calls == 1
        stats = _limiters[model.model_key].stats()
        assert stats["total_rate_limited"] == 0
        assert stats["is_paused"] is False
    finally:
        _limiters.clear()


@pytest.mark.asyncio
async def test_stream_rate_limit_under_cap_still_retries() -> None:
    """A Retry-After below the cap keeps the existing pause-and-retry."""
    _limiters.clear()
    try:
        inner = _RateLimitStreamModel("0.05")
        model = _build_rate_limit_model(inner)

        result = await model(messages=[{"role": "user", "content": "hi"}])
        stream = cast(AsyncGenerator[Any, None], result)
        chunks = [chunk async for chunk in stream]

        assert [chunk.content for chunk in chunks] == ["ok"]
        assert inner.calls == 2
        stats = _limiters[model.model_key].stats()
        assert stats["total_rate_limited"] == 1
    finally:
        _limiters.clear()
