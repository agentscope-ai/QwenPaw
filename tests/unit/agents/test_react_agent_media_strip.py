# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent media classification, stripping, and retry.

Covers _is_media_block (dict/object/data-block detection) and
_strip_media_blocks_from_memory (top-level media removal, nested
tool_result output filtering, empty-content placeholder insertion), plus
request-only recovery from provider media-payload rejections.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

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
from qwenpaw.constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.providers.model_capability_cache import get_capability_cache


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


def _agent_with_context(context: list) -> QwenPawAgent:
    """Build a bare agent with only a state.context — no model needed."""
    agent = object.__new__(QwenPawAgent)
    agent.state = SimpleNamespace(context=context)
    return agent


def _msg_with(blocks: list) -> Msg:
    """Build a Msg whose content is assigned raw (bypassing block
    validation) so dict media blocks can be inspected by the strip logic."""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="seed")],
    )
    msg.content = blocks
    return msg


def _reasoning_agent() -> QwenPawAgent:
    """Build the attributes read by the reasoning retry wrapper."""
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


def _media_data_block() -> DataBlock:
    """Build an inline image block accepted by AgentScope validation."""
    return DataBlock(
        source=Base64Source(
            media_type="image/png",
            data="aGVsbG8=",
        ),
    )


def _current_media_context() -> list[Msg]:
    return [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text="look"),
                _media_data_block(),
            ],
        ),
    ]


def _tool_media_context() -> list[Msg]:
    tool_result = ToolResultBlock(
        id="call-image",
        name="screenshot",
        state=ToolResultState.SUCCESS,
        output="seed",
    )
    tool_result.output = [_media_data_block()]
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


def _historical_media_context() -> list[Msg]:
    return [
        *_current_media_context(),
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


def _dump_context(context: list[Msg]) -> list[dict]:
    """Return the complete stored context for mutation checks."""
    return [msg.model_dump(mode="json") for msg in context]


def _formatter(wire_media_count: int = 1) -> SimpleNamespace:
    """Build the formatter state used by media fallback tests."""
    return SimpleNamespace(
        _qwenpaw_last_wire_media_count=wire_media_count,
        _qwenpaw_last_wire_audio_count=0,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )


# ---------------------------------------------------------------------------
# _is_media_block
# ---------------------------------------------------------------------------


class TestIsMediaBlock:
    def test_dict_image_is_media(self):
        agent = _agent_with_context([])
        assert agent._is_media_block({"type": "image"}) is True
        assert agent._is_media_block({"type": "audio"}) is True
        assert agent._is_media_block({"type": "video"}) is True
        assert agent._is_media_block({"type": "file"}) is True

    def test_dict_text_not_media(self):
        agent = _agent_with_context([])
        assert agent._is_media_block({"type": "text"}) is False

    def test_object_block_by_type(self):
        agent = _agent_with_context([])
        assert agent._is_media_block(SimpleNamespace(type="image")) is True
        assert agent._is_media_block(SimpleNamespace(type="text")) is False

    def test_data_block_image_mime_is_media(self):
        agent = _agent_with_context([])
        source = SimpleNamespace(media_type="image/png")
        assert (
            agent._is_media_block(
                SimpleNamespace(type="data", source=source),
            )
            is True
        )

    def test_data_block_non_media_mime_not_media(self):
        agent = _agent_with_context([])
        source = SimpleNamespace(media_type="application/json")
        assert (
            agent._is_media_block(
                SimpleNamespace(type="data", source=source),
            )
            is False
        )

    def test_data_block_without_source_not_media(self):
        agent = _agent_with_context([])
        assert (
            agent._is_media_block(
                SimpleNamespace(type="data", source=None),
            )
            is False
        )


class TestMediaCapabilityErrors:
    def test_nested_file_error_allows_media_fallback(self):
        error = RuntimeError(
            "Error code: 400 - file must have a file_id or file_data",
        )

        assert QwenPawAgent._is_explicit_media_capability_error(error) is True

    def test_nested_file_error_does_not_poison_global_capability(self):
        error = RuntimeError(
            "Error code: 400 - file must have a file_id or file_data",
        )

        assert QwenPawAgent._is_global_media_capability_error(error) is False


# ---------------------------------------------------------------------------
# _strip_media_blocks_from_memory
# ---------------------------------------------------------------------------


class TestStripMediaBlocksFromMemory:
    def test_strips_top_level_media(self):
        msg = _msg_with(
            [
                TextBlock(type="text", text="keep"),
                {"type": "image", "source": {}},
            ],
        )
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        assert len(msg.content) == 1
        assert msg.content[0].text == "keep"

    def test_non_list_content_skipped(self):
        msg = _msg_with([])
        msg.content = "plain string"
        agent = _agent_with_context([msg])
        assert agent._strip_media_blocks_from_memory() == 0

    def test_empty_content_gets_placeholder(self):
        msg = _msg_with([{"type": "image", "source": {}}])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        assert len(msg.content) == 1
        assert msg.content[0].text == MEDIA_UNSUPPORTED_PLACEHOLDER

    def test_no_media_returns_zero(self):
        msg = _msg_with([TextBlock(type="text", text="plain")])
        agent = _agent_with_context([msg])
        assert agent._strip_media_blocks_from_memory() == 0
        assert len(msg.content) == 1

    def test_nested_media_in_tool_result_stripped(self):
        tool_result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output="seed",
        )
        # Assign raw nested output (bypassing block validation) so a
        # dict media item can be inspected by the strip logic.
        tool_result.output = [
            TextBlock(type="text", text="kept"),
            {"type": "image", "source": {}},
        ]
        msg = _msg_with([tool_result])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        # the media item removed from nested output
        assert len(tool_result.output) == 1
        assert tool_result.output[0].text == "kept"

    def test_nested_all_media_replaced_with_placeholder(self):
        tool_result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output="seed",
        )
        tool_result.output = [{"type": "image", "source": {}}]
        msg = _msg_with([tool_result])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        assert tool_result.output == MEDIA_UNSUPPORTED_PLACEHOLDER

    def test_nested_output_not_list_untouched(self):
        tool_result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output="plain string output",
        )
        msg = _msg_with([tool_result])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 0
        assert tool_result.output == "plain string output"

    def test_counts_across_messages(self):
        msg1 = _msg_with([{"type": "image", "source": {}}])
        msg2 = _msg_with(
            [
                TextBlock(type="text", text="ok"),
                {"type": "video", "source": {}},
            ],
        )
        agent = _agent_with_context([msg1, msg2])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 2


# ---------------------------------------------------------------------------
# request-only retry for media payload rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR, True),
        (
            "Error code: 400 - unsupported image format: application/x-tiff",
            True,
        ),
        ("Error code: 400 - invalid image data in messages[3].image[0]", True),
        ("Error code: 400 - failed to decode the audio payload", True),
        ("Error code: 400 - multiple image inputs are not supported", True),
        (_MODEL_CAPABILITY_ERROR, False),
        (
            "Error code: 400 - image is sensitive: invalid image content",
            False,
        ),
        ("Error code: 400 - resolution not supported", False),
        ("Error code: 400 - invalid request", False),
    ],
)
def test_media_payload_rejection_classifier(
    error: str,
    expected: bool,
) -> None:
    """Classify payload failures without matching capability errors."""
    assert (
        QwenPawAgent._is_media_payload_rejection_error(RuntimeError(error))
        is expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context_factory",
    [
        _current_media_context,
        _tool_media_context,
        _historical_media_context,
    ],
    ids=["current-media", "tool-media", "historical-media"],
)
async def test_payload_rejection_uses_request_only_retry(
    monkeypatch,
    context_factory,
) -> None:
    """Strip retry media without changing current or historical context."""
    cache = get_capability_cache()
    cache.clear()
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="deepseek:deepseek-v4-flash")
    agent.state.context = context_factory()
    original_context = agent.state.context
    original_dump = _dump_context(original_context)
    agent.formatter = _formatter()
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
async def test_failed_payload_retry_preserves_context(monkeypatch) -> None:
    """A failed media-free retry must not corrupt persisted history."""
    agent = _reasoning_agent()
    agent.state.context = _current_media_context()
    original_context = agent.state.context
    original_dump = _dump_context(original_context)
    agent.formatter = _formatter()
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
@pytest.mark.parametrize(
    ("wire_media_count", "has_formatter"),
    [(0, True), (1, False)],
    ids=["no-wire-media", "no-formatter"],
)
async def test_payload_rejection_without_safe_retry_raises(
    monkeypatch,
    wire_media_count: int,
    has_formatter: bool,
) -> None:
    """Do not retry when the request cannot be safely normalized."""
    agent = _reasoning_agent()
    agent.state.context = _current_media_context()
    original_dump = _dump_context(agent.state.context)
    agent._uses_request_time_media_normalization = lambda: has_formatter
    agent.formatter = _formatter(wire_media_count)
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
