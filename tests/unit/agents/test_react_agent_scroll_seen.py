# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for Scroll's successful-model-input acknowledgement hook."""

from types import SimpleNamespace

import pytest
from agentscope.agent import Agent
from agentscope.event import ModelCallEndEvent
from agentscope.message import HintBlock, Msg, TextBlock
from agentscope.model import FinishedReason

from qwenpaw.agents.react_agent import (
    QwenPawAgent,
    _EXPLICIT_UNSUPPORTED_MEDIA_PATTERNS,
)
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.providers.model_capability_cache import get_capability_cache

_AUDIO_MODAL_ERROR = (
    "Error code: 400 - {'error': {'message': '<400> "
    "InternalError.Algo.InvalidParameter: An incorrect modal `audio` was "
    "entered, which may not be supported by the model or was placed in the "
    "wrong position (e.g., in system/assistant).', "
    "'type': 'invalid_request_error'}}"
)

_AUDIO_INPUT_PART_ERROR = (
    "Error code: 422 - {'error': {'message': "
    '"Failed to deserialize the JSON body into the target type: '
    "messages[88]: unknown variant `input_audio`, expected one of "
    '`text`, `image_url`, `file`"}}'
)

# LM Studio (OpenAI-compatible, audio limit = 0).
_LM_STUDIO_AUDIO_LIMIT_ERROR = (
    "Error code: 400 - {'error': {'message': 'At most 0 audio(s) may be "
    "provided in one prompt. (parameter=audio)', 'type': 'BadRequestError', "
    "'param': 'audio', 'code': 400}}"
)

_LM_STUDIO_IMAGE_LIMIT_ERROR = (
    "Error code: 400 - {'error': {'message': 'At most 0 image(s) may be "
    "provided in one prompt. (parameter=image)', 'type': 'BadRequestError', "
    "'param': 'image', 'code': 400}}"
)

_LM_STUDIO_VIDEO_LIMIT_ERROR = (
    "Error code: 400 - {'error': {'message': 'At most 0 video(s) may be "
    "provided in one prompt. (parameter=video)', 'type': 'BadRequestError', "
    "'param': 'video', 'code': 400}}"
)

_ENDPOINT_MEDIA_DISABLED_ERROR = (
    "Error code: 400 - {'error': {'type': 'server_error', 'message': "
    "'Upstream request failed: [unsupported_request] Message content "
    "supports text content only. Images, audio and files are not enabled.'}}"
)


class _FakeAPIError(Exception):
    """Provider error that exposes a structured HTTP status code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class SeenTracker:
    """Minimal Scroll manager surface used by ``QwenPawAgent._reasoning``."""

    def __init__(self) -> None:
        self.acknowledged: list[set[str]] = []
        self.thinking_acknowledged: list[set[str]] = []

    @staticmethod
    def model_input_tool_result_ids(agent) -> set[str]:
        return {"call-seen"}

    def acknowledge_model_input_tool_results(self, ids: set[str]) -> None:
        self.acknowledged.append(set(ids))

    @staticmethod
    def model_input_thinking_block_ids(agent) -> set[str]:
        return {"thinking-seen"}

    def acknowledge_model_input_thinking_blocks(self, ids: set[str]) -> None:
        self.thinking_acknowledged.append(set(ids))


class CompressionTracker:
    """Capture context-manager compression delegation arguments."""

    def __init__(self) -> None:
        self.calls = []

    async def compress(self, agent, context_config=None, instructions=None):
        self.calls.append((agent, context_config, instructions))


class ThinkingOmissionModel:
    """Record explicit thinking omission calls from the agent."""

    def __init__(self) -> None:
        self.ids: set[str] | None = None

    def set_thinking_omit_ids(self, block_ids: set[str]) -> bool:
        self.ids = set(block_ids)
        return True


def make_agent(tracker: SeenTracker) -> QwenPawAgent:
    """Build only the attributes the reasoning wrapper reads."""
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = tracker
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent.state = SimpleNamespace(context=[], reply_id="reply")
    agent.name = "agent"
    agent.model = SimpleNamespace(model_key=None)
    agent._model_rejects_media = lambda: False
    agent._uses_request_time_media_normalization = lambda: False

    async def stop_handlers(final_msg):
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            final_message=final_msg,
        )

    agent._run_stop_handlers = stop_handlers
    return agent


def test_thinking_omissions_delegate_to_model_wrapper() -> None:
    """Fallback-aware model interfaces take precedence over one formatter."""
    agent = object.__new__(QwenPawAgent)
    model = ThinkingOmissionModel()
    agent.model = model
    agent.formatter = SimpleNamespace()

    applied = agent._set_formatter_thinking_omit_ids({"thinking-1"})

    assert applied is True
    assert model.ids == {"thinking-1"}
    assert not hasattr(agent.formatter, "_qwenpaw_omit_thinking_ids")


async def test_successful_model_call_acknowledges_input_results(monkeypatch):
    tracker = SeenTracker()
    agent = make_agent(tracker)

    async def successful_reasoning(self, tool_choice=None):
        yield ModelCallEndEvent(
            reply_id="reply",
            input_tokens=10,
            output_tokens=2,
            finished_reason=FinishedReason.COMPLETED,
        )
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="done")],
        )

    monkeypatch.setattr(Agent, "_reasoning", successful_reasoning)
    events = [event async for event in agent._reasoning()]

    assert tracker.acknowledged == [{"call-seen"}]
    assert tracker.thinking_acknowledged == [{"thinking-seen"}]
    assert isinstance(events[-1], Msg)


async def test_failed_model_call_does_not_acknowledge_results(monkeypatch):
    tracker = SeenTracker()
    agent = make_agent(tracker)

    async def failed_reasoning(self, tool_choice=None):
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError("provider rejected request")

    monkeypatch.setattr(Agent, "_reasoning", failed_reasoning)

    with pytest.raises(RuntimeError, match="provider rejected request"):
        async for _ in agent._reasoning():
            pass

    assert not tracker.acknowledged
    assert not tracker.thinking_acknowledged


async def test_interrupted_model_call_does_not_acknowledge_results(
    monkeypatch,
):
    tracker = SeenTracker()
    agent = make_agent(tracker)

    async def interrupted_reasoning(self, tool_choice=None):
        yield ModelCallEndEvent(
            reply_id="reply",
            input_tokens=10,
            output_tokens=0,
            finished_reason=FinishedReason.INTERRUPTED,
        )

    monkeypatch.setattr(Agent, "_reasoning", interrupted_reasoning)
    events = [event async for event in agent._reasoning()]

    assert len(events) == 1
    assert not tracker.acknowledged
    assert not tracker.thinking_acknowledged


async def test_compress_context_forwards_one_shot_instructions():
    tracker = CompressionTracker()
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = tracker
    agent._compress_context_middlewares = []
    agent.state = SimpleNamespace(context=[])
    config = SimpleNamespace(trigger_ratio=0.1)
    instructions = HintBlock(hint="prioritize failures", source="user")

    await agent.compress_context(config, instructions=instructions)

    assert tracker.calls == [(agent, config, instructions)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_error", "model_key"),
    [
        (_AUDIO_MODAL_ERROR, "dashscope:qwen3.7-plus"),
        (_LM_STUDIO_AUDIO_LIMIT_ERROR, "lmstudio:local-audio-limit"),
    ],
    ids=["dashscope-modal", "lmstudio-at-most-audio"],
)
async def test_audio_modal_error_strips_audio_and_retries_once(
    monkeypatch,
    provider_error: str,
    model_key: str,
) -> None:
    cache = get_capability_cache()
    cache.clear()
    agent = make_agent(SeenTracker())
    agent.model = SimpleNamespace(model_key=model_key)
    agent._uses_request_time_media_normalization = lambda: True
    agent.formatter = SimpleNamespace(
        _qwenpaw_last_wire_media_count=1,
        _qwenpaw_last_wire_audio_count=1,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(provider_error)
        # Retry strips audio only. The next turn strips proactively.
        assert agent.formatter._qwenpaw_force_strip_audio is True
        assert agent.formatter._qwenpaw_force_strip_media is False
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="done")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    try:
        events = [event async for event in agent._reasoning()]
        next_events = [event async for event in agent._reasoning()]

        assert calls == 3
        assert isinstance(events[-1], Msg)
        assert isinstance(next_events[-1], Msg)
        assert cache.get(model_key, "rejects_audio", False) is True
        assert cache.get(model_key, "rejects_media", False) is False
        assert agent.formatter._qwenpaw_force_strip_audio is False
        assert agent.formatter._qwenpaw_force_strip_media is False
    finally:
        cache.clear()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_AUDIO_MODAL_ERROR, True),
        (_AUDIO_INPUT_PART_ERROR, True),
        (
            "Error code: 422 - unknown variant `input_text`, expected one of "
            "`text`, `image_url`, `file`",
            False,
        ),
        (_LM_STUDIO_AUDIO_LIMIT_ERROR, True),
        (
            "At most 0 audio(s) may be provided in one prompt.",
            True,
        ),
        (
            "At most 2 audios may be provided in one prompt.",
            True,
        ),
        (
            "Error code: 400 - {'error': {'message': 'At most 0 audio(s) "
            "allowed.', 'param': 'audio', 'code': 400}}",
            True,
        ),
        (_LM_STUDIO_IMAGE_LIMIT_ERROR, False),
        (_LM_STUDIO_VIDEO_LIMIT_ERROR, False),
        (_ENDPOINT_MEDIA_DISABLED_ERROR, False),
        (
            "Error code: 400 - This model's maximum context length is "
            "8192 tokens.",
            False,
        ),
        ("Error code: 500 - internal server error", False),
        (
            "Error code: 400 - failed to decode image data in "
            "messages[3].image[0]",
            False,
        ),
        (
            "Error code: 400 - invalid image: could not decode the image",
            False,
        ),
        (
            "Error code: 400 - This model does not support image input.",
            False,
        ),
        ("Error code: 400 - at most 0 audio files were accepted", False),
        ("Error code: 400 - invalid value (parameter=audio)", False),
    ],
)
def test_audio_fallback_error_classifies_unknown_audio_parts(
    error: str,
    expected: bool,
) -> None:
    """Recognize unsupported audio payloads without broad status matches."""
    assert (
        QwenPawAgent._is_audio_fallback_error(RuntimeError(error)) is expected
    )


def test_lmstudio_audio_limit_matches_structured_status_code() -> None:
    """A status_code attribute is not required, but must not block a match."""
    with_status = _FakeAPIError(_LM_STUDIO_AUDIO_LIMIT_ERROR, status_code=400)
    inner_only = _FakeAPIError(
        "At most 0 audio(s) may be provided in one prompt. (parameter=audio)",
        status_code=400,
    )
    assert QwenPawAgent._is_audio_fallback_error(with_status) is True
    assert QwenPawAgent._is_audio_fallback_error(inner_only) is True


def test_lmstudio_audio_limit_does_not_learn_global_media_rejection() -> None:
    """An audio count cap is not a model-wide multimodal capability loss."""
    exc = RuntimeError(_LM_STUDIO_AUDIO_LIMIT_ERROR)
    normalized = " ".join(str(exc).lower().split())
    assert not any(
        pattern.search(normalized) or pattern.search(str(exc).lower())
        for pattern in _EXPLICIT_UNSUPPORTED_MEDIA_PATTERNS
    )
    assert QwenPawAgent._is_explicit_media_capability_error(exc) is False
    assert QwenPawAgent._is_global_media_capability_error(exc) is False
    assert QwenPawAgent._is_media_payload_rejection_error(exc) is True
    image_exc = RuntimeError(_LM_STUDIO_IMAGE_LIMIT_ERROR)
    assert QwenPawAgent._is_audio_fallback_error(image_exc) is False
    assert QwenPawAgent._is_media_payload_rejection_error(image_exc) is True
    assert QwenPawAgent._is_global_media_capability_error(image_exc) is False


@pytest.mark.parametrize(
    "error",
    [
        _LM_STUDIO_VIDEO_LIMIT_ERROR,
        _LM_STUDIO_IMAGE_LIMIT_ERROR,
        _ENDPOINT_MEDIA_DISABLED_ERROR,
    ],
    ids=["at-most-video", "at-most-image", "are-not-enabled"],
)
def test_media_at_most_and_disabled_stay_off_audio_path(error: str) -> None:
    """Video/image at-most and are-not-enabled use media payload, not audio."""
    exc = RuntimeError(error)
    assert QwenPawAgent._is_audio_fallback_error(exc) is False
    assert QwenPawAgent._is_media_payload_rejection_error(exc) is True
    assert QwenPawAgent._is_explicit_media_capability_error(exc) is False
    assert QwenPawAgent._is_global_media_capability_error(exc) is False
