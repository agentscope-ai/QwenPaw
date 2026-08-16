# -*- coding: utf-8 -*-
"""Regression tests for issue #7059 (view_video on OpenAI Responses API).

Two independent defects were fixed:
- ``promote_tool_result_images`` was passed to the agentscope 2.0 formatter
  constructor via kwargs, where the field no longer exists (1.x leftover) and
  Pydantic silently dropped it, so video promotion never ran.
- ``_promote_tool_result_videos`` only matched ``tool_call_id``, but the
  OpenAI Responses API emits ``call_id``, so promotion never fired there.
"""

# pylint: disable=protected-access
from types import SimpleNamespace
from unittest.mock import patch

from agentscope.formatter import (
    GeminiChatFormatter,
    OpenAIChatFormatter,
    OpenAIResponseFormatter,
)

from qwenpaw.agents import model_factory
from qwenpaw.agents.model_factory import _promote_tool_result_videos


class _FakeModel:
    """Minimal ChatModelBase stand-in carrying a real formatter."""

    def __init__(self, formatter) -> None:
        self.formatter = formatter


class _FakeMsg:
    """Minimal Msg stand-in with ``content`` list."""

    def __init__(self, content) -> None:
        self.content = content
        self.role = "tool"


def _video_tool_result_block() -> dict:
    return {
        "type": "tool_result",
        "id": "call_abc123",
        "name": "view_video",
        "output": [
            {
                "type": "video",
                "source": {
                    "type": "url",
                    "media_type": "video/mp4",
                    "url": "file:///tmp/v.mp4",
                },
            },
        ],
    }


def _count_promoted(messages: list[dict]) -> int:
    return sum(
        1
        for m in messages
        if m.get("role") == "user"
        and "video contents" in str(m.get("content"))
    )


# --------------------------------------------------------------------- 1b


def test_promote_matches_responses_call_id() -> None:
    """OpenAI Responses format uses ``call_id`` — must be matched."""
    msgs = [_FakeMsg([_video_tool_result_block()])]
    messages = [
        {"role": "assistant", "content": "...", "tool_calls": []},
        {
            "type": "function_call_output",
            "call_id": "call_abc123",
            "output": "Video loaded: v.mp4",
        },
    ]
    with patch(
        "qwenpaw.agents.model_factory._format_openai_video_block",
        return_value={"type": "input_video", "video_url": {"url": "x"}},
    ):
        out = _promote_tool_result_videos(msgs, messages, response_api=True)

    assert _count_promoted(out) == 1


def test_promote_still_matches_chat_tool_call_id() -> None:
    """OpenAI chat format uses ``tool_call_id`` — must keep working."""
    msgs = [_FakeMsg([_video_tool_result_block()])]
    messages = [
        {"role": "assistant", "content": "...", "tool_calls": []},
        {"role": "tool", "tool_call_id": "call_abc123", "content": "Video"},
    ]
    with patch(
        "qwenpaw.agents.model_factory._format_openai_video_block",
        return_value={"type": "video_url", "video_url": {"url": "x"}},
    ):
        out = _promote_tool_result_videos(msgs, messages, response_api=False)

    assert _count_promoted(out) == 1


def test_promote_skips_unmatched_ids() -> None:
    """No promotion when the wire message id does not match any tool result."""
    msgs = [_FakeMsg([_video_tool_result_block()])]
    messages = [
        {"role": "assistant", "content": "...", "tool_calls": []},
        {
            "type": "function_call_output",
            "call_id": "call_OTHER",
            "output": "Video loaded",
        },
    ]
    out = _promote_tool_result_videos(msgs, messages, response_api=True)

    assert _count_promoted(out) == 0
    assert len(out) == len(messages)


# --------------------------------------------------------------------- 1a


def test_create_formatter_instance_sets_promote_flag() -> None:
    """The promote flag must land on the instance, not be dropped by Pydantic."""
    model = _FakeModel(OpenAIResponseFormatter())
    formatter = model_factory._create_formatter_instance(
        model,
        provider_id="test",
    )
    assert getattr(formatter, "promote_tool_result_images", False) is True


def test_create_formatter_instance_openai_chat_sets_flag() -> None:
    model = _FakeModel(OpenAIChatFormatter())
    formatter = model_factory._create_formatter_instance(
        model,
        provider_id="test",
    )
    assert getattr(formatter, "promote_tool_result_images", False) is True


def test_create_formatter_instance_gemini_sets_flag() -> None:
    model = _FakeModel(GeminiChatFormatter())
    formatter = model_factory._create_formatter_instance(
        model,
        provider_id="test",
    )
    assert getattr(formatter, "promote_tool_result_images", False) is True


def test_create_formatter_instance_anthropic_no_flag() -> None:
    """Anthropic keeps images natively — no promotion flag expected."""
    from agentscope.formatter import AnthropicChatFormatter

    model = _FakeModel(AnthropicChatFormatter())
    formatter = model_factory._create_formatter_instance(
        model,
        provider_id="test",
    )
    assert getattr(formatter, "promote_tool_result_images", False) is False


def test_create_formatter_instance_returns_wrapped_class() -> None:
    """The returned formatter must still be a FileBlockSupport wrapper."""
    model = _FakeModel(OpenAIResponseFormatter())
    formatter = model_factory._create_formatter_instance(
        model,
        provider_id="test",
    )
    assert type(formatter).__name__.startswith("FileBlockSupport")
    assert isinstance(formatter, OpenAIResponseFormatter)
    # Plain formatting still works end-to-end
    assert formatter.input_types is not None
