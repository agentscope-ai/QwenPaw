# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Recovery tests for provider-side media payload rejections.

A provider that refuses the media *bytes* — an unsupported container, an
image it cannot decode, dimensions it will not accept — must not be mistaken
for a model without multimodal capability. Such a rejection is retried with
a media-free request while the original context stays intact.
"""
from types import SimpleNamespace

import pytest
from agentscope.agent import Agent
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
    ToolResultBlock,
    ToolResultState,
)

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.providers.model_capability_cache import get_capability_cache


# Verbatim answer from DeepSeek for an image whose side exceeds its 8192 px
# limit: the message names neither the limit nor the model's capability.
_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR = (
    "Error code: 400 - {'error': {'message': 'Failed to deserialize the "
    "JSON body into the target type: messages[106].image[0]: You have "
    "uploaded an unsupported image. Please make sure your image is valid "
    "and has one of the following formats: webp, png, jpeg, and gif.'}}"
)

_MODEL_CAPABILITY_ERROR = (
    "Error code: 400 - {'error': {'message': 'This model does not support "
    "image input.'}}"
)


def _make_agent() -> QwenPawAgent:
    """Build only the attributes the reasoning wrapper reads."""
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = None
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent.state = SimpleNamespace(context=[], reply_id="reply")
    agent.name = "agent"
    agent.model = SimpleNamespace(model_key=None)
    agent._model_rejects_media = lambda: False
    agent._uses_request_time_media_normalization = lambda: True

    async def stop_handlers(final_msg):
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            final_message=final_msg,
        )

    agent._run_stop_handlers = stop_handlers
    return agent


def _media_block() -> DataBlock:
    """A DataBlock-shaped image payload, as stored in tool results."""
    return DataBlock(
        source=Base64Source(
            media_type="image/png",
            data="aGVsbG8=",
        ),
    )


def _context_with_media() -> list:
    return [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text="look"),
                _media_block(),
            ],
        ),
    ]


def _context_with_tool_media() -> list:
    tool_result = ToolResultBlock(
        id="call-image",
        name="screenshot",
        state=ToolResultState.SUCCESS,
        output="seed",
    )
    tool_result.output = [_media_block()]
    return [
        Msg(
            name="agent",
            role="assistant",
            content=[
                TextBlock(type="text", text="calling screenshot"),
                tool_result,
            ],
        ),
    ]


def _context_with_historical_media() -> list:
    return [
        *_context_with_media(),
        Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="accepted")],
        ),
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="plain follow-up")],
        ),
    ]


def _dump_context(context: list) -> list[dict]:
    """Return the complete stored context for mutation checks."""
    return [msg.model_dump(mode="json") for msg in context]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR, True),
        (
            "Error code: 400 - unsupported image format: application/x-tiff",
            True,
        ),
        ("Error code: 400 - invalid image data in messages[3].image[0]", True),
        ("Error code: 400 - image dimensions exceed the allowed limit", True),
        ("Error code: 400 - failed to decode the audio payload", True),
        # Request-scoped media limits that upstream already names.
        (
            "Error code: 400 - multiple image inputs are not supported",
            True,
        ),
        ("Error code: 400 - image resolution is too high", True),
        ("Error code: 400 - video duration exceeds the limit", True),
        # Capability rejections belong to the capability classifier.
        (_MODEL_CAPABILITY_ERROR, False),
        (
            "Error code: 400 - unknown variant `image_url`, expected one of "
            "`text`, `file`",
            False,
        ),
        # Content safety is never a payload problem, even when the same
        # message also carries an asset signal.
        (
            "Error code: 400 - image is sensitive: invalid image content",
            False,
        ),
        # A payload signal without a media noun must not match.
        ("Error code: 400 - failed to decode base64 payload", False),
        ("Error code: 400 - resolution not supported", False),
        ("Error code: 400 - invalid request", False),
    ],
)
def test_media_payload_rejection_classifier(
    error: str,
    expected: bool,
) -> None:
    """Classify asset-level rejections without matching capability errors."""
    assert (
        QwenPawAgent._is_media_payload_rejection_error(RuntimeError(error))
        is expected
    )


@pytest.mark.parametrize(
    "error",
    [
        _DEEPSEEK_UNSUPPORTED_IMAGE_ERROR,
        "Error code: 400 - invalid image data in messages[3].image[0]",
    ],
)
def test_asset_rejections_are_not_learned_as_capability_loss(
    error: str,
) -> None:
    """An asset-level failure must never poison the capability cache."""
    assert (
        QwenPawAgent._is_explicit_media_capability_error(RuntimeError(error))
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context_factory",
    [
        _context_with_media,
        _context_with_tool_media,
        _context_with_historical_media,
    ],
    ids=["current-media", "tool-media", "historical-media"],
)
async def test_unsupported_image_payload_uses_request_only_retry(
    monkeypatch,
    context_factory,
) -> None:
    """Retry strips request media without changing stored history."""
    cache = get_capability_cache()
    cache.clear()
    agent = _make_agent()
    agent.model = SimpleNamespace(model_key="deepseek:deepseek-v4-flash")
    agent.state.context = context_factory()
    original_context = agent.state.context
    original_dump = _dump_context(original_context)
    agent.formatter = SimpleNamespace(
        _qwenpaw_last_wire_media_count=1,
        _qwenpaw_last_wire_audio_count=0,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)
        assert agent.formatter._qwenpaw_force_strip_media is True
        assert agent.formatter._qwenpaw_force_strip_audio is False
        assert agent.state.context is original_context
        assert _dump_context(agent.state.context) == original_dump
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    try:
        events = [event async for event in agent._reasoning()]

        assert calls == 2
        assert isinstance(events[-1], Msg)
        assert agent.state.context is original_context
        assert _dump_context(agent.state.context) == original_dump
        # The model itself is fine: no capability loss may be cached.
        assert (
            cache.get(
                "deepseek:deepseek-v4-flash",
                "rejects_media",
                False,
            )
            is False
        )
        assert agent.formatter._qwenpaw_force_strip_media is False
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_failed_recovery_restores_original_context(monkeypatch) -> None:
    """A failed media-free retry must not corrupt persisted history."""
    agent = _make_agent()
    agent.state.context = _context_with_media()
    original_context = agent.state.context
    original_dump = _dump_context(original_context)
    agent.formatter = SimpleNamespace(
        _qwenpaw_last_wire_media_count=1,
        _qwenpaw_last_wire_audio_count=0,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError("retry failed")

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="retry failed"):
        async for _ in agent._reasoning():
            pass

    assert calls == 2
    assert agent.state.context is original_context
    assert _dump_context(agent.state.context) == original_dump
    assert agent.formatter._qwenpaw_force_strip_media is False


@pytest.mark.asyncio
async def test_payload_rejection_without_formatter_raises(monkeypatch) -> None:
    """Without request normalization, history is not mutated for recovery."""
    agent = _make_agent()
    agent.state.context = _context_with_media()
    original_dump = _dump_context(agent.state.context)
    agent._uses_request_time_media_normalization = lambda: False
    agent.formatter = SimpleNamespace(
        _qwenpaw_last_wire_media_count=1,
        _qwenpaw_last_wire_audio_count=0,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="unsupported image"):
        async for _ in agent._reasoning():
            pass

    assert calls == 1
    assert _dump_context(agent.state.context) == original_dump


@pytest.mark.asyncio
async def test_payload_rejection_without_media_in_flight_raises(
    monkeypatch,
) -> None:
    """Without media on the wire the error keeps its original handling."""
    agent = _make_agent()
    agent.formatter = SimpleNamespace(
        _qwenpaw_last_wire_media_count=0,
        _qwenpaw_last_wire_audio_count=0,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )

    async def provider_reasoning(self, tool_choice=None):
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="unsupported image"):
        async for _ in agent._reasoning():
            pass
