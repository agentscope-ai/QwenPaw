# -*- coding: utf-8 -*-
"""Tests for cross-model fallback boundaries."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, cast

import pytest
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse, StructuredResponse
from agentscope.model._model_usage import ChatUsage

from qwenpaw.providers.fallback_chat_model import (
    FallbackChatModel,
    install_fallback_notice_sink,
)
from qwenpaw.providers.rate_limiter import _limiters
from qwenpaw.providers.retry_chat_model import (
    RateLimitConfig,
    RetryChatModel,
    RetryConfig,
)
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


class FakeModel(ChatModelBase):
    """Minimal model with injectable behavior."""

    def __init__(
        self,
        name: str,
        behavior: Any,
        *,
        context_size: int = 32_768,
        provider_id: str = "",
    ) -> None:
        super().__init__(
            credential=None,
            model=name,
            parameters=ChatModelBase.Parameters(),
            stream=True,
            context_size=context_size,
        )
        self.behavior = behavior
        self.calls = 0
        self._provider_id = provider_id

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior()

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return await self(*args, **kwargs)


class _FakeFormatter:
    """Minimal stand-in for a QwenPaw formatter."""

    def __init__(self, media_types: list[str]) -> None:
        self.supported_input_media_types = media_types


class HttpError(Exception):
    """Exception carrying an HTTP status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


async def _stream(
    *items: ChatResponse,
    error: Exception | None = None,
) -> AsyncGenerator[ChatResponse, None]:
    for item in items:
        yield item
    if error is not None:
        raise error


async def _idle_stream(
    state: dict[str, int],
) -> AsyncGenerator[ChatResponse, None]:
    try:
        await asyncio.Event().wait()
        yield _response("unreachable")
    finally:
        state["closed"] += 1


def _response(text: str) -> ChatResponse:
    return ChatResponse(
        content=[{"type": "text", "text": text}],
        is_last=True,
    )


async def test_falls_back_on_transient_error_before_output() -> None:
    primary = FakeModel("primary", HttpError(503))
    fallback = FakeModel("fallback", lambda: _stream(_response("ok")))
    model = FallbackChatModel([primary, fallback])

    response = await model(messages=[], tools=[])
    chunks = [chunk async for chunk in response]

    assert chunks[0].content[0]["text"] == "ok"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert chunks[0].metadata["qwenpaw_model_fallbacks"] == [
        {
            "type": "model_fallback",
            "from_provider_id": "",
            "from_model_id": "primary",
            "to_provider_id": "",
            "to_model_id": "fallback",
            "reason_kind": "transient",
        },
    ]


async def test_stream_idle_timeout_falls_back_after_retries() -> None:
    _limiters.clear()
    state = {"closed": 0}
    try:
        primary = FakeModel(
            "primary",
            lambda: _idle_stream(state),
        )
        retried_primary = RetryChatModel(
            primary,
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
        fallback = FakeModel(
            "fallback",
            lambda: _stream(_response("ok")),
        )
        model = FallbackChatModel([retried_primary, fallback])

        response = await model(messages=[], tools=[])
        chunks = [chunk async for chunk in response]

        assert chunks[-1].content[0]["text"] == "ok"
        assert primary.calls == 2
        assert fallback.calls == 1
        assert state["closed"] == 2
        assert chunks[-1].metadata["qwenpaw_model_fallbacks"] == [
            {
                "type": "model_fallback",
                "from_provider_id": "",
                "from_model_id": "primary",
                "to_provider_id": "",
                "to_model_id": "fallback",
                "reason_kind": "transient",
            },
        ]
    finally:
        _limiters.clear()


async def test_falls_back_when_primary_model_is_not_found() -> None:
    primary = FakeModel(
        "retired-primary",
        HttpError(404),
        provider_id="primary-provider",
    )
    fallback = FakeModel(
        "fallback",
        lambda: _response("fallback-ok"),
        provider_id="fallback-provider",
    )
    model = FallbackChatModel([primary, fallback])

    response = await model(messages=[], tools=[])

    assert response.content[0]["text"] == "fallback-ok"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert response.metadata["qwenpaw_model_fallbacks"] == [
        {
            "type": "model_fallback",
            "from_provider_id": "primary-provider",
            "from_model_id": "retired-primary",
            "to_provider_id": "fallback-provider",
            "to_model_id": "fallback",
            "reason_kind": "model_not_found",
        },
    ]


@pytest.mark.parametrize(
    ("primary_size", "fallback_size"),
    [
        (128_000, 1_000_000),
        (1_000_000, 128_000),
    ],
)
async def test_identity_and_context_follow_fallback(
    primary_size: int,
    fallback_size: int,
) -> None:
    primary = FakeModel(
        "primary",
        HttpError(429),
        context_size=primary_size,
        provider_id="primary-provider",
    )
    fallback = FakeModel(
        "fallback",
        lambda: _response("ok"),
        context_size=fallback_size,
        provider_id="fallback-provider",
    )
    model = FallbackChatModel([primary, fallback])

    response = await model(messages=[], tools=[])

    assert response.content[0]["text"] == "ok"
    # During the request the response metadata reports the serving model;
    # once the request settles, identity resets to the primary so the
    # compaction budget and capability learning size for the model the
    # NEXT request will try first.
    actual = response.metadata["qwenpaw_actual_model"]
    assert actual["model_id"] == "fallback"
    assert actual["context_size"] == fallback_size
    assert model.model == "primary"
    assert model.context_size == primary_size
    assert response.metadata["qwenpaw_model_fallbacks"] == [
        {
            "type": "model_fallback",
            "from_provider_id": "primary-provider",
            "from_model_id": "primary",
            "to_provider_id": "fallback-provider",
            "to_model_id": "fallback",
            "reason_kind": "rate_limited",
        },
    ]


async def test_does_not_fallback_after_stream_output() -> None:
    primary = FakeModel(
        "primary",
        lambda: _stream(_response("partial"), error=HttpError(503)),
    )
    fallback = FakeModel("fallback", lambda: _stream(_response("unused")))
    model = FallbackChatModel([primary, fallback])

    response = await model(messages=[], tools=[])
    with pytest.raises(HttpError):
        _ = [chunk async for chunk in response]

    assert fallback.calls == 0


async def test_falls_back_after_empty_stream_control_chunk() -> None:
    primary = FakeModel(
        "primary",
        lambda: _stream(
            ChatResponse(
                content=[{"type": "text", "text": ""}],
                is_last=False,
            ),
            error=HttpError(503),
        ),
    )
    fallback = FakeModel("fallback", lambda: _stream(_response("ok")))
    model = FallbackChatModel([primary, fallback])

    response = await model(messages=[], tools=[])
    chunks = [chunk async for chunk in response]

    assert chunks[-1].content[0]["text"] == "ok"
    assert fallback.calls == 1


async def test_skips_fallback_that_fails_before_returning_stream() -> None:
    primary = FakeModel(
        "primary",
        lambda: _stream(error=HttpError(503)),
    )
    first_fallback = FakeModel("first-fallback", HttpError(429))
    second_fallback = FakeModel(
        "second-fallback",
        lambda: _stream(_response("ok")),
    )
    model = FallbackChatModel(
        [primary, first_fallback, second_fallback],
    )

    response = await model(messages=[], tools=[])
    chunks = [chunk async for chunk in response]

    assert chunks[-1].content[0]["text"] == "ok"
    assert first_fallback.calls == 1
    assert second_fallback.calls == 1


async def test_does_not_fallback_on_authentication_error() -> None:
    primary = FakeModel("primary", HttpError(401))
    fallback = FakeModel("fallback", lambda: _stream(_response("unused")))
    model = FallbackChatModel([primary, fallback])

    with pytest.raises(HttpError):
        await model(messages=[], tools=[])

    assert fallback.calls == 0


class ClosableModel(FakeModel):
    """Model that records closure of its active provider stream."""

    def __init__(self) -> None:
        super().__init__("closable", self._stream)
        self.closed = False
        self.cancelled = False
        self.generator_exited = False
        self.release = asyncio.Event()

    async def _stream(self) -> AsyncGenerator[ChatResponse, None]:
        try:
            yield ChatResponse(
                content=[{"type": "text", "text": "partial"}],
                is_last=False,
            )
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        except GeneratorExit:
            self.generator_exited = True
            raise
        finally:
            self.closed = True


def _full_wrapper_chain(inner: ChatModelBase) -> FallbackChatModel:
    recorded = TokenRecordingModelWrapper("unit", inner)
    retried = RetryChatModel(
        recorded,
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(
            max_concurrent=1,
            max_qpm=0,
            pause_seconds=1.0,
            jitter_range=0.0,
            acquire_timeout=10.0,
        ),
    )
    return FallbackChatModel([retried])


async def test_abandoned_full_wrapper_chain_closes_provider_stream() -> None:
    _limiters.clear()
    try:
        inner = ClosableModel()
        model = _full_wrapper_chain(inner)
        result = await model(messages=[], tools=[])
        stream = cast(AsyncGenerator[ChatResponse, None], result)

        await anext(stream)
        await stream.aclose()

        assert inner.closed is True
        assert inner.generator_exited is True
    finally:
        _limiters.clear()


async def test_cancelled_full_wrapper_chain_closes_provider_stream() -> None:
    _limiters.clear()
    try:
        inner = ClosableModel()
        wrapped = _full_wrapper_chain(inner)
        fallback = FakeModel(
            "fallback",
            lambda: _stream(_response("unused")),
        )
        model = FallbackChatModel([wrapped, fallback])
        result = await model(messages=[], tools=[])
        stream = cast(AsyncGenerator[ChatResponse, None], result)

        await anext(stream)
        pending = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        assert inner.cancelled is True
        assert inner.closed is True
        assert fallback.calls == 0
    finally:
        _limiters.clear()


async def test_each_request_starts_from_primary_model() -> None:
    primary = FakeModel(
        "primary",
        lambda: _stream(error=HttpError(503)),
    )
    fallback = FakeModel("fallback", lambda: _stream(_response("ok")))
    model = FallbackChatModel([primary, fallback])

    for _ in range(2):
        response = await model(messages=[], tools=[])
        _ = [chunk async for chunk in response]

    assert primary.calls == 2
    assert fallback.calls == 2


async def test_concurrent_requests_keep_fallback_state_isolated() -> None:
    primary = FakeModel(
        "primary",
        lambda: _stream(error=HttpError(503)),
    )
    fallback = FakeModel("fallback", lambda: _stream(_response("ok")))
    model = FallbackChatModel([primary, fallback])

    async def consume() -> list[ChatResponse]:
        response = await model(messages=[], tools=[])
        return [chunk async for chunk in response]

    results = await asyncio.gather(consume(), consume())

    assert [result[-1].content[0]["text"] for result in results] == [
        "ok",
        "ok",
    ]
    assert primary.calls == 2
    assert fallback.calls == 2


async def test_concurrent_requests_keep_active_metadata_isolated() -> None:
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    call_count = 0

    async def primary_stream():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await first_release.wait()
            raise HttpError(503)
        await second_release.wait()
        yield _response("primary-ok")

    primary = FakeModel(
        "primary",
        primary_stream,
        context_size=128_000,
        provider_id="primary-provider",
    )
    fallback = FakeModel(
        "fallback",
        lambda: _stream(_response("fallback-ok")),
        context_size=1_000_000,
        provider_id="fallback-provider",
    )
    model = FallbackChatModel([primary, fallback])

    async def consume_first():
        response = await model(messages=[], tools=[])
        first_release.set()
        chunks = []
        during = []
        async for chunk in response:
            chunks.append(chunk)
            during.append((model.model_key, model.context_size))
        return chunks[-1], during[-1]

    async def consume_second():
        response = await model(messages=[], tools=[])
        second_release.set()
        chunks = []
        during = []
        async for chunk in response:
            chunks.append(chunk)
            during.append((model.model_key, model.context_size))
        return chunks[-1], during[-1]

    first, second = await asyncio.gather(consume_first(), consume_second())

    # While each stream is live, the tasks see their own serving model.
    assert first[1] == ("fallback", 1_000_000)
    assert second[1] == ("primary", 128_000)
    # After both requests settle, identity is back on the primary.
    assert model.model_key == "primary"
    assert model.context_size == 128_000
    assert first[0].metadata["qwenpaw_actual_model"] == {
        "provider_id": "fallback-provider",
        "model_id": "fallback",
        "context_size": 1_000_000,
    }
    assert second[0].metadata["qwenpaw_actual_model"] == {
        "provider_id": "primary-provider",
        "model_id": "primary",
        "context_size": 128_000,
    }


async def test_usage_and_model_key_follow_actual_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_session_id",
        lambda: "fallback-session",
    )
    primary = FakeModel("primary", HttpError(503))
    fallback = FakeModel(
        "fallback",
        lambda: _stream(
            ChatResponse(
                content=[{"type": "text", "text": "ok"}],
                is_last=True,
                usage=ChatUsage(
                    input_tokens=7,
                    output_tokens=3,
                    time=0.1,
                ),
            ),
        ),
    )
    wrapped_primary = TokenRecordingModelWrapper("primary-provider", primary)
    wrapped_fallback = TokenRecordingModelWrapper(
        "fallback-provider",
        fallback,
    )
    model = FallbackChatModel([wrapped_primary, wrapped_fallback])

    response = await model(messages=[], tools=[])
    _ = [chunk async for chunk in response]
    usage = TokenRecordingModelWrapper.pop_usage_for_session(
        "fallback-session",
    )

    # Usage is attributed per slot by TokenRecordingModelWrapper; the
    # wrapper's own identity resets to the primary once the stream ends.
    assert model.model_key == "primary"
    assert usage is not None
    assert usage["provider_id"] == "fallback-provider"
    assert usage["model_name"] == "fallback"


async def test_structured_output_reports_multi_hop_fallback() -> None:
    primary = FakeModel(
        "primary",
        HttpError(503),
        provider_id="primary-provider",
    )
    first_fallback = FakeModel(
        "first-fallback",
        HttpError(429),
        provider_id="first-provider",
    )
    final_fallback = FakeModel(
        "final-fallback",
        lambda: StructuredResponse(content={"answer": "ok"}),
        context_size=1_000_000,
        provider_id="final-provider",
    )
    model = FallbackChatModel(
        [primary, first_fallback, final_fallback],
    )

    response = await model.generate_structured_output(messages=[], tools=[])

    assert response.content == {"answer": "ok"}
    assert response.metadata["qwenpaw_model_fallbacks"] == [
        {
            "type": "model_fallback",
            "from_provider_id": "primary-provider",
            "from_model_id": "primary",
            "to_provider_id": "first-provider",
            "to_model_id": "first-fallback",
            "reason_kind": "transient",
        },
        {
            "type": "model_fallback",
            "from_provider_id": "first-provider",
            "from_model_id": "first-fallback",
            "to_provider_id": "final-provider",
            "to_model_id": "final-fallback",
            "reason_kind": "rate_limited",
        },
    ]
    assert response.metadata["qwenpaw_actual_model"] == {
        "provider_id": "final-provider",
        "model_id": "final-fallback",
        "context_size": 1_000_000,
    }
    assert model.model == "primary"
    assert model.context_size == 32_768


async def test_structured_output_rejects_ineligible_failure() -> None:
    primary = FakeModel("primary", HttpError(401))
    fallback = FakeModel(
        "fallback",
        lambda: StructuredResponse(content={"unused": True}),
    )
    model = FallbackChatModel([primary, fallback])

    with pytest.raises(HttpError):
        await model.generate_structured_output(messages=[], tools=[])

    assert fallback.calls == 0


async def test_concurrent_structured_fallback_events_are_isolated() -> None:
    primary = FakeModel("primary", HttpError(503))
    fallback = FakeModel(
        "fallback",
        lambda: StructuredResponse(content={"answer": "ok"}),
    )
    model = FallbackChatModel([primary, fallback])

    responses = await asyncio.gather(
        model.generate_structured_output(messages=[], tools=[]),
        model.generate_structured_output(messages=[], tools=[]),
    )

    assert all(
        len(response.metadata["qwenpaw_model_fallbacks"]) == 1
        for response in responses
    )
    assert responses[0].metadata is not responses[1].metadata


async def test_broken_candidate_does_not_block_rest_of_chain() -> None:
    """A revoked-key candidate must not mask healthy models behind it."""
    primary = FakeModel("primary", HttpError(429))
    revoked = FakeModel("revoked", HttpError(401))
    healthy = FakeModel("healthy", lambda: _response("ok"))
    model = FallbackChatModel([primary, revoked, healthy])

    response = await model()

    assert revoked.calls == 1
    assert healthy.calls == 1
    events = response.metadata["qwenpaw_model_fallbacks"]
    assert [event["to_model_id"] for event in events] == [
        "revoked",
        "healthy",
    ]
    actual = response.metadata["qwenpaw_actual_model"]
    assert actual["model_id"] == "healthy"


async def test_structured_output_skips_broken_candidate() -> None:
    primary = FakeModel("primary", HttpError(503))
    revoked = FakeModel("revoked", HttpError(401))
    healthy = FakeModel(
        "healthy",
        lambda: StructuredResponse(content={"answer": "ok"}),
    )
    model = FallbackChatModel([primary, revoked, healthy])

    response = await model.generate_structured_output(messages=[], tools=[])

    assert healthy.calls == 1
    events = response.metadata["qwenpaw_model_fallbacks"]
    assert len(events) == 2


async def test_fallback_sink_records_events_and_actual_model() -> None:
    """The reply loop reads fallback data from the request sink."""
    sink = install_fallback_notice_sink()
    primary = FakeModel("primary", HttpError(429))
    fallback = FakeModel("fallback", lambda: _response("ok"))
    model = FallbackChatModel([primary, fallback])

    await model()

    assert len(sink["events"]) == 1
    assert sink["events"][0]["type"] == "model_fallback"
    assert sink["events"][0]["to_model_id"] == "fallback"
    assert (sink["actual_model"] or {})["model_id"] == "fallback"


async def test_active_model_resets_after_streamed_fallback() -> None:
    """The last-served fallback must not leak past the stream's end."""
    primary = FakeModel(
        "primary",
        HttpError(503),
        context_size=32_768,
    )
    fallback = FakeModel(
        "fallback",
        lambda: _stream(_response("ok")),
        context_size=262_144,
    )
    model = FallbackChatModel([primary, fallback])

    response = await model(messages=[], tools=[])
    during: list[tuple[str, int]] = []
    async for _chunk in cast(AsyncGenerator[ChatResponse, None], response):
        during.append((model.model, model.context_size))

    # While the fallback serves the stream, identity follows it ...
    assert during == [("fallback", 262_144)]
    # ... and once the stream settles it resets to the primary, which
    # the next request tries first (compaction must budget for it).
    assert model.model == "primary"
    assert model.context_size == 32_768
    assert model.model_key == "primary"


async def test_active_model_resets_when_all_models_fail() -> None:
    primary = FakeModel("primary", HttpError(503), context_size=32_768)
    fallback = FakeModel("fallback", HttpError(503), context_size=262_144)
    model = FallbackChatModel([primary, fallback])

    with pytest.raises(HttpError):
        await model(messages=[], tools=[])

    assert model.model == "primary"
    assert model.context_size == 32_768


async def test_active_model_resets_after_structured_fallback() -> None:
    primary = FakeModel("primary", HttpError(429), context_size=32_768)
    fallback = FakeModel(
        "fallback",
        lambda: StructuredResponse(content={"answer": "ok"}),
        context_size=262_144,
    )
    model = FallbackChatModel([primary, fallback])

    await model.generate_structured_output(messages=[], tools=[])

    assert model.model == "primary"
    assert model.context_size == 32_768


async def test_late_close_of_abandoned_stream_keeps_primary_active() -> None:
    """Out-of-order token resets must not reinstate the leaked model.

    Scenario: request 1's stream is abandoned without closing (token
    still owned by the suspended generator), request 2 starts in the
    same task, the abandoned stream is closed mid-request-2, and
    request 2 then finishes.  CPython restores an outdated token's
    snapshot silently, so without the invariant enforcement request 2's
    reset would reinstate request 1's leaked fallback model.
    """
    primary = FakeModel("primary", HttpError(503), context_size=32_768)
    fallback = FakeModel(
        "fallback",
        lambda: _stream(_response("one"), _response("two")),
        context_size=262_144,
    )
    model = FallbackChatModel([primary, fallback])

    stream1 = await model(messages=[], tools=[])
    first = await stream1.__anext__()
    assert first.content[0]["text"] == "one"

    primary.behavior = lambda: _stream(_response("ok"))
    stream2 = await model(messages=[], tools=[])
    await stream1.aclose()
    _ = [chunk async for chunk in stream2]

    assert model.model == "primary"
    assert model.context_size == 32_768


def test_fallback_wrapper_exposes_active_model_formatter() -> None:
    """AgentScope can inspect media support on the outermost model.

    ``ChatModelBase`` declares no formatter, so an unforwarded attribute
    lookup raises instead of degrading to a default instance.
    """
    primary = FakeModel("primary", lambda: _response("ok"))
    fallback = FakeModel("fallback", lambda: _response("ok"))
    primary_formatter = _FakeFormatter(["image/*"])
    fallback_formatter = _FakeFormatter([])
    primary.formatter = primary_formatter
    fallback.formatter = fallback_formatter
    model = FallbackChatModel([primary, fallback])

    assert model.formatter is primary_formatter
    assert model.formatter.supported_input_media_types == ["image/*"]

    # Identity follows the model serving the request, so a fallback that
    # supports different media reports its own capabilities.
    model._activate_model(fallback)  # pylint: disable=protected-access
    assert model.formatter is fallback_formatter


def test_fallback_formatter_assignment_reaches_provider_model() -> None:
    """Installing a formatter traverses Retry and Token wrappers."""
    provider_model = FakeModel("primary", lambda: _response("ok"))
    provider_model.formatter = _FakeFormatter([])
    wrapped = RetryChatModel(
        TokenRecordingModelWrapper(provider_id="unit", model=provider_model),
        retry_config=RetryConfig(enabled=False),
    )
    fallback = FakeModel("fallback", lambda: _response("ok"))
    fallback.formatter = _FakeFormatter([])
    model = FallbackChatModel([wrapped, fallback])

    replacement = _FakeFormatter(["video/*"])
    model.formatter = replacement

    assert provider_model.formatter is replacement
    assert model.formatter is replacement
    # The idle fallback keeps its own formatter until it serves a request.
    assert fallback.formatter is not replacement
