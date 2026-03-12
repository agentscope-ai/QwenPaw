# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, AsyncGenerator, cast

import httpx
from agentscope.model import ChatModelBase

from copaw.providers.retry_chat_model import RetryChatModel, _is_retryable


def test_is_retryable_for_httpx_remote_protocol_error() -> None:
    exc = httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body",
    )
    assert _is_retryable(exc) is True


def test_is_retryable_for_wrapped_remote_protocol_error() -> None:
    try:
        try:
            raise httpx.RemoteProtocolError("incomplete chunked read")
        except httpx.RemoteProtocolError as inner:
            raise RuntimeError("wrapped error") from inner
    except RuntimeError as outer:
        assert _is_retryable(outer) is True


async def test_retry_stream_when_remote_protocol_error(
    monkeypatch,
) -> None:
    class _FakeInnerModel:
        model_name = "fake"
        stream = True

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, *args: Any, **kwargs: Any):
            _ = args, kwargs
            self.calls += 1
            if self.calls == 1:

                async def _fail_stream():
                    raise httpx.RemoteProtocolError("incomplete chunked read")
                    yield  # pragma: no cover

                return _fail_stream()

            async def _ok_stream():
                yield {"ok": True}

            return _ok_stream()

    async def _no_sleep(_: float) -> None:
        return None

    import copaw.providers.retry_chat_model as retry_module

    monkeypatch.setattr(retry_module, "LLM_MAX_RETRIES", 1)
    monkeypatch.setattr(retry_module.asyncio, "sleep", _no_sleep)

    model = RetryChatModel(cast(ChatModelBase, _FakeInnerModel()))
    result = cast(AsyncGenerator[Any, None], await model("hello"))

    chunks = []
    async for chunk in result:
        chunks.append(chunk)

    assert chunks == [{"ok": True}]
