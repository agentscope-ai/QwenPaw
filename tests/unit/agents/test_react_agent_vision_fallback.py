# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent._try_vision_fallback integration point.

These tests exercise the agent-side glue that reads the
``multimodal_fallback`` running config, extracts the session id, invokes
``describe_images_in_messages`` and degrades gracefully on error. They use
a lightweight stub as ``self`` so the heavy QwenPawAgent constructor does
not need to run.
"""
# pylint: disable=protected-access,unused-argument

import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from agentscope.event import (
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import AssistantMsg, Msg, TextBlock

from qwenpaw.agents.react_agent import QwenPawAgent

# describe_images_in_messages is imported lazily inside the method, so the
# patch target is the source module attribute.
_DESCRIBE_PATH = (
    "qwenpaw.agents.utils.vision_fallback.describe_images_in_messages"
)


def _make_fb(enabled: bool = True) -> SimpleNamespace:
    """Build a stub MultimodalFallbackConfig-like object."""
    return SimpleNamespace(
        enabled=enabled,
        vision_provider="dashscope",
        vision_model="qwen-vl-max",
        max_image_descriptions=5,
        description_max_tokens=300,
        system_prompt="Describe.",
    )


def _make_agent_stub(
    fb,
    context=None,
    request_context=None,
) -> SimpleNamespace:
    """Build a stub with only the attributes _try_vision_fallback needs."""
    return SimpleNamespace(
        _agent_config=SimpleNamespace(
            running=SimpleNamespace(multimodal_fallback=fb),
        ),
        _request_context=request_context,
        state=SimpleNamespace(context=context if context is not None else []),
    )


class TestTryVisionFallback:
    """Tests for the _try_vision_fallback integration method."""

    @pytest.mark.asyncio
    async def test_disabled_returns_zero_without_call(self):
        """When fallback is disabled, describe must not be called."""
        stub = _make_agent_stub(_make_fb(enabled=False))
        with patch(_DESCRIBE_PATH, new=AsyncMock()) as mock_desc:
            result = await QwenPawAgent._try_vision_fallback(stub)
        assert result == (0, [])
        mock_desc.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_config_returns_zero(self):
        """When multimodal_fallback is None, describe must not be called."""
        stub = _make_agent_stub(None)
        with patch(_DESCRIBE_PATH, new=AsyncMock()) as mock_desc:
            result = await QwenPawAgent._try_vision_fallback(stub)
        assert result == (0, [])
        mock_desc.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_invokes_describe_with_config(self):
        """Enabled fallback forwards a deep-copied context and session id."""
        ctx = [object()]
        stub = _make_agent_stub(
            _make_fb(enabled=True),
            context=ctx,
            request_context={"session_id": "sess-1"},
        )
        mock_desc = AsyncMock(return_value=2)
        with patch(_DESCRIBE_PATH, new=mock_desc):
            result = await QwenPawAgent._try_vision_fallback(stub)

        described, context_copy = result
        assert described == 2
        # The method must return the mutated copy, not the original context.
        assert context_copy is not ctx
        mock_desc.assert_awaited_once()
        args, kwargs = mock_desc.call_args
        # describe_images_in_messages receives a deep copy of the context.
        assert args[0] is context_copy
        assert args[0] is not ctx
        assert kwargs["vision_provider_id"] == "dashscope"
        assert kwargs["vision_model"] == "qwen-vl-max"
        assert kwargs["max_images"] == 5
        assert kwargs["max_tokens"] == 300
        assert kwargs["system_prompt"] == "Describe."
        assert kwargs["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_enabled_does_not_mutate_original_context(self):
        """The original conversation history must remain unmodified."""
        original_block = {"type": "image", "url": "http://example.com/a.png"}
        ctx = [SimpleNamespace(content=[original_block])]
        stub = _make_agent_stub(
            _make_fb(enabled=True),
            context=ctx,
        )

        async def _fake_describe(msgs, **kwargs):
            # Simulate the in-place mutation that vision_fallback performs.
            for msg in msgs:
                msg.content = [{"type": "text", "text": "described"}]
            return 1

        with patch(_DESCRIBE_PATH, new=_fake_describe):
            await QwenPawAgent._try_vision_fallback(stub)

        # Original context still has the image block; UI sees the image.
        assert ctx[0].content == [original_block]

    @pytest.mark.asyncio
    async def test_exception_returns_zero(self):
        """A failing vision call degrades gracefully to 0 (media strip)."""
        stub = _make_agent_stub(
            _make_fb(enabled=True),
            request_context={"session_id": "s"},
        )
        mock_desc = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(_DESCRIBE_PATH, new=mock_desc):
            result = await QwenPawAgent._try_vision_fallback(stub)
        assert result == (0, [])

    @pytest.mark.asyncio
    async def test_none_request_context_yields_none_session(self):
        """A missing request context results in session_id=None."""
        stub = _make_agent_stub(
            _make_fb(enabled=True),
            request_context=None,
        )
        mock_desc = AsyncMock(return_value=0)
        with patch(_DESCRIBE_PATH, new=mock_desc):
            await QwenPawAgent._try_vision_fallback(stub)
        _, kwargs = mock_desc.call_args
        assert kwargs["session_id"] is None


def _make_reasoning_stub(
    context: list[Msg] | None = None,
    fb=None,
) -> SimpleNamespace:
    """Build a stub that can run QwenPawAgent._reasoning."""
    stub = SimpleNamespace(
        _agent_config=SimpleNamespace(
            running=SimpleNamespace(multimodal_fallback=fb or _make_fb()),
        ),
        _request_context={"session_id": "sess-1"},
        name="agent",
        state=SimpleNamespace(
            context=context if context is not None else [],
            reply_id="reply-1",
        ),
    )
    stub._model_rejects_media = lambda: False
    stub._uses_request_time_media_normalization = lambda: False
    stub._get_model_key = lambda: None
    stub._is_bad_request_or_media_error = lambda exc: False
    stub._proactive_strip_media_blocks = lambda: 0
    stub._set_formatter_media_strip = lambda enabled: None
    stub._run_stop_handlers = AsyncMock(
        return_value=SimpleNamespace(action="stop"),
    )
    # Will be replaced by tests that exercise the model-call path.
    stub._call_base_reasoning = AsyncMock()
    return stub


class TestReasoningContextIsolation:
    """Tests that _reasoning keeps UI history clean while feeding the model."""

    @pytest.mark.asyncio
    async def test_assistant_reply_merged_back_to_original_context(self):
        """Model sees descriptions, but original context keeps image + reply."""
        original_block = {"type": "image", "url": "http://example.com/a.png"}
        user_msg = SimpleNamespace(
            role="user",
            name="user",
            content=[original_block],
        )
        original_context = [user_msg]

        # Vision fallback produces a copy where the image is replaced.
        context_copy = [
            SimpleNamespace(
                role="user",
                name="user",
                content=[{"type": "text", "text": "described"}],
            ),
        ]
        stub = _make_reasoning_stub(context=original_context)

        async def _fake_base_reasoning(self, tool_choice=None):
            # Simulate agentscope appending the assistant reply to the
            # currently active context (which is the description copy).
            self.state.context.append(
                AssistantMsg(
                    name="agent",
                    content=[TextBlock(text="reply")],
                ),
            )
            yield TextBlockStartEvent(
                reply_id=self.state.reply_id,
                block_id="b1",
            )
            yield TextBlockDeltaEvent(
                reply_id=self.state.reply_id,
                block_id="b1",
                delta="reply",
            )
            yield TextBlockEndEvent(
                reply_id=self.state.reply_id,
                block_id="b1",
            )
            yield AssistantMsg(
                name="agent",
                content=[TextBlock(text="reply")],
            )

        # Bind the mocked methods directly on the stub so they resolve from
        # the instance dictionary (the stub is not a real QwenPawAgent).
        stub._try_vision_fallback = AsyncMock(return_value=(1, context_copy))
        stub._call_base_reasoning = types.MethodType(
            _fake_base_reasoning,
            stub,
        )

        events = []
        async for evt in QwenPawAgent._reasoning(stub):
            events.append(evt)

        # Original context must keep the image (for UI/persistence) and also
        # receive the assistant reply produced during the model call.
        assert len(stub.state.context) == 2
        assert stub.state.context[0] is user_msg
        assert stub.state.context[0].content == [original_block]
        assert isinstance(stub.state.context[1], Msg)
        assert stub.state.context[1].role == "assistant"
