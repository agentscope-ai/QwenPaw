# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring
# pylint: disable=use-implicit-booleaness-not-comparison
"""Tests for fallback chat model wrapper."""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

import pytest

from agentscope.model import ChatModelBase, ChatResponse

from qwenpaw.providers.fallback_chat_model import (
    FallbackCandidate,
    FallbackChatModel,
    ModelFallbackError,
)
from qwenpaw.providers.retry_chat_model import RetryChatModel, RetryConfig


def _response(text: str) -> ChatResponse:
    return ChatResponse(
        content=[{"type": "text", "text": text}],
        is_last=True,
    )


def _retryable_error(message: str = "retryable") -> Exception:
    exc = Exception(message)
    exc.status_code = 500  # type: ignore[attr-defined]
    return exc


def _model_access_error(message: str = "model unsupported") -> Exception:
    exc = Exception(message)
    exc.status_code = 401  # type: ignore[attr-defined]
    return exc


class FakeChatModel(ChatModelBase):
    """Test double that returns a value or raises a configured exception."""

    # pylint: disable=too-few-public-methods

    def __init__(self, name: str, behavior: Any) -> None:
        super().__init__(
            credential=None,
            model=name,
            parameters=None,
            stream=False,
        )
        self.behavior = behavior
        self.calls = 0

    async def __call__(self, *args: Any, **kwargs: Any):
        del args, kwargs
        self.calls += 1
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


class FakeStreamModel(ChatModelBase):
    """Test double that yields configured events or raises mid-stream."""

    # pylint: disable=too-few-public-methods

    def __init__(self, name: str, events: list[Any]) -> None:
        super().__init__(
            credential=None,
            model=name,
            parameters=None,
            stream=True,
        )
        self.events = events
        self.calls = 0

    async def __call__(self, *args: Any, **kwargs: Any):
        del args, kwargs
        self.calls += 1
        return self._stream()

    async def _stream(self) -> AsyncGenerator[ChatResponse, None]:
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event


def _candidate(provider_id: str, model: ChatModelBase) -> FallbackCandidate:
    return FallbackCandidate(
        provider_id=provider_id,
        model_name=getattr(model, "model", "unknown"),
        model=model,
    )


@pytest.mark.asyncio
async def test_primary_success_does_not_call_fallback() -> None:
    primary = FakeChatModel("primary", _response("primary"))
    fallback = FakeChatModel("fallback", _response("fallback"))
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    result = await model(messages=[])

    assert result.content[0]["text"] == "primary"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_retryable_primary_failure_uses_fallback() -> None:
    primary = FakeChatModel("primary", _retryable_error())
    fallback = FakeChatModel("fallback", _response("fallback"))
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    result = await model(messages=[])

    assert result.content[0]["text"] == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_model_access_failure_uses_fallback_without_retrying() -> None:
    primary = FakeChatModel("primary", _model_access_error())
    fallback = FakeChatModel("fallback", _response("fallback"))
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    result = await model(messages=[])

    assert result.content[0]["text"] == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_multiple_fallback_candidates_are_tried_in_order() -> None:
    primary = FakeChatModel("primary", _retryable_error("primary failed"))
    fallback_1 = FakeChatModel("fallback_1", _retryable_error("f1 failed"))
    fallback_2 = FakeChatModel("fallback_2", _response("fallback_2"))
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback_1),
            _candidate("p2", fallback_2),
        ],
    )

    result = await model(messages=[])

    assert result.content[0]["text"] == "fallback_2"
    assert [primary.calls, fallback_1.calls, fallback_2.calls] == [1, 1, 1]


@pytest.mark.asyncio
async def test_all_retryable_candidates_fail_with_aggregate_error() -> None:
    primary = FakeChatModel("primary", _retryable_error("primary failed"))
    fallback = FakeChatModel("fallback", _retryable_error("fallback failed"))
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    with pytest.raises(ModelFallbackError) as caught:
        await model(messages=[])

    assert "p0:primary" in str(caught.value)
    assert "p1:fallback" in str(caught.value)
    assert "primary failed" not in str(caught.value)
    assert "fallback failed" not in str(caught.value)
    assert "status_code=500" in str(caught.value)


@pytest.mark.asyncio
async def test_non_retryable_error_does_not_fallback() -> None:
    primary_error = ValueError("bad request")
    primary = FakeChatModel("primary", primary_error)
    fallback = FakeChatModel("fallback", _response("fallback"))
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    with pytest.raises(ValueError):
        await model(messages=[])

    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_retry_before_fallback_logs_safe_error_summary(caplog) -> None:
    leaked = "SECRET_PROMPT api_key=sk-test request-body"
    primary = RetryChatModel(
        FakeChatModel("primary", _retryable_error(leaked)),
        retry_config=RetryConfig(
            enabled=True,
            max_retries=1,
            backoff_base=0.0,
            backoff_cap=0.0,
        ),
    )
    fallback = RetryChatModel(
        FakeChatModel("fallback", _response("fallback")),
        retry_config=RetryConfig(
            enabled=True,
            max_retries=1,
            backoff_base=0.0,
            backoff_cap=0.0,
        ),
    )
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    with caplog.at_level(logging.WARNING):
        result = await model(messages=[])

    assert result.content[0]["text"] == "fallback"
    assert leaked not in caplog.text
    assert "Exception(status_code=500)" in caplog.text


@pytest.mark.asyncio
async def test_stream_failure_before_first_chunk_uses_fallback() -> None:
    primary = FakeStreamModel("primary", [_retryable_error("stream start")])
    fallback = FakeStreamModel("fallback", [_response("fallback")])
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    stream = await model(messages=[])
    chunks = [chunk async for chunk in stream]

    assert [chunk.content[0]["text"] for chunk in chunks] == ["fallback"]
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_stream_failure_after_first_chunk_does_not_fallback() -> None:
    primary = FakeStreamModel(
        "primary",
        [_response("partial"), _retryable_error("mid stream")],
    )
    fallback = FakeStreamModel("fallback", [_response("fallback")])
    model = FallbackChatModel(
        [
            _candidate("p0", primary),
            _candidate("p1", fallback),
        ],
    )

    stream = await model(messages=[])
    seen = []
    with pytest.raises(Exception, match="mid stream"):
        async for chunk in stream:
            seen.append(chunk.content[0]["text"])

    assert seen == ["partial"]
    assert primary.calls == 1
    assert fallback.calls == 0
