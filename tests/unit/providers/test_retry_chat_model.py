# -*- coding: utf-8 -*-
from __future__ import annotations

import copaw.providers.retry_chat_model as retry_chat_model_module
from copaw.providers.retry_chat_model import RetryChatModel, RetryConfig


class RetryableError(RuntimeError):
    def __init__(self, message: str = "retry me", status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code


class FakeChatModel:
    def __init__(self, results, stream: bool = False):
        self.model_name = "fake-model"
        self.stream = stream
        self._results = iter(results)
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        _ = args, kwargs
        self.calls += 1
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


async def test_retry_chat_model_retries_transient_failures(monkeypatch):
    delays = []
    expected = object()

    async def fake_sleep(delay):
        delays.append(delay)

    inner = FakeChatModel(
        [RetryableError("first"), RetryableError("second"), expected],
    )
    monkeypatch.setattr(retry_chat_model_module.asyncio, "sleep", fake_sleep)

    model = RetryChatModel(
        inner,
        retry_config=RetryConfig(
            enabled=True,
            max_retries=2,
            backoff_base=0.5,
            backoff_cap=2.0,
        ),
    )

    result = await model("hello")

    assert result is expected
    assert inner.calls == 3
    assert delays == [0.5, 1.0]


async def test_retry_chat_model_respects_disabled_toggle(monkeypatch):
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    inner = FakeChatModel([RetryableError("boom")])
    monkeypatch.setattr(retry_chat_model_module.asyncio, "sleep", fake_sleep)

    model = RetryChatModel(
        inner,
        retry_config=RetryConfig(
            enabled=False,
            max_retries=5,
            backoff_base=0.5,
            backoff_cap=2.0,
        ),
    )

    try:
        await model("hello")
    except RetryableError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("RetryableError was not raised")

    assert inner.calls == 1
    assert not delays


async def test_retry_chat_model_retries_failed_stream(monkeypatch):
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    class FailOnNext:
        def __iter__(self):
            return self

        def __next__(self):
            raise RetryableError("stream failed")

    async def failing_stream():
        for chunk in FailOnNext():
            yield chunk

    async def successful_stream():
        yield "chunk-1"
        yield "chunk-2"

    inner = FakeChatModel([failing_stream(), successful_stream()], stream=True)
    monkeypatch.setattr(retry_chat_model_module.asyncio, "sleep", fake_sleep)

    model = RetryChatModel(
        inner,
        retry_config=RetryConfig(
            enabled=True,
            max_retries=1,
            backoff_base=0.25,
            backoff_cap=1.0,
        ),
    )

    chunks = []
    async for chunk in await model("hello"):
        chunks.append(chunk)

    assert chunks == ["chunk-1", "chunk-2"]
    assert inner.calls == 2
    assert delays == [0.25]
