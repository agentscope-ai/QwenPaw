# -*- coding: utf-8 -*-
"""Tests for completed background tool-call hint messages."""

import uuid
from types import SimpleNamespace

import pytest
from agentscope.formatter import (
    AnthropicChatFormatter,
    GeminiChatFormatter,
    OpenAIChatFormatter,
    OpenAIResponseFormatter,
)
from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultState,
)
from agentscope.tool import ToolResponse

from qwenpaw.tool_calls._hint import make_offload_hint_msg


_NOTIFICATION = (
    "<system-notification>\n"
    "Background tool call `slow_tool` (id=call-bg) completed with "
    "state=success. The full result follows in the next tool_result block.\n"
    "</system-notification>"
)


@pytest.fixture(name="offload_hint")
def _offload_hint():
    """Build a representative completed background tool-call hint."""
    response = ToolResponse(
        content=[TextBlock(type="text", text="done")],
        id="call-bg",
        state=ToolResultState.SUCCESS,
    )
    entry = SimpleNamespace(
        end_state="success",
        ctx=SimpleNamespace(
            tool_call_id="call-bg",
            tool_name="slow_tool",
        ),
        final_response=response,
    )
    return make_offload_hint_msg(entry)


def test_offload_hint_pairs_tool_call_and_result(offload_hint) -> None:
    assert [block.type for block in offload_hint.content] == [
        "text",
        "tool_call",
        "tool_result",
    ]

    tool_call = offload_hint.content[1]
    assert isinstance(tool_call, ToolCallBlock)
    assert tool_call.id != "call-bg"
    assert len(tool_call.id) == 32
    assert uuid.UUID(tool_call.id).hex == tool_call.id
    assert tool_call.name == "slow_tool"
    assert tool_call.input == "{}"
    assert tool_call.state == ToolCallState.FINISHED
    assert offload_hint.content[2].id == tool_call.id


@pytest.mark.asyncio
async def test_offload_hint_formats_for_openai(offload_hint) -> None:
    formatted = await OpenAIChatFormatter().format([offload_hint])
    hint_call_id = offload_hint.content[1].id

    assert formatted == [
        {
            "role": "assistant",
            "name": "system",
            "content": [{"type": "text", "text": _NOTIFICATION}],
            "tool_calls": [
                {
                    "id": hint_call_id,
                    "type": "function",
                    "function": {
                        "name": "slow_tool",
                        "arguments": "{}",
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": hint_call_id,
            "content": "done",
            "name": "slow_tool",
        },
    ]


@pytest.mark.asyncio
async def test_offload_hint_formats_for_openai_responses(offload_hint) -> None:
    formatted = await OpenAIResponseFormatter().format([offload_hint])
    hint_call_id = offload_hint.content[1].id

    assert formatted == [
        {
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": _NOTIFICATION},
            ],
        },
        {
            "type": "function_call",
            "call_id": hint_call_id,
            "name": "slow_tool",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": hint_call_id,
            "output": "done",
        },
    ]


@pytest.mark.asyncio
async def test_offload_hint_formats_for_anthropic(offload_hint) -> None:
    formatted = await AnthropicChatFormatter().format([offload_hint])
    hint_call_id = offload_hint.content[1].id

    assert formatted == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": _NOTIFICATION},
                {
                    "type": "tool_use",
                    "id": hint_call_id,
                    "name": "slow_tool",
                    "input": {},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": hint_call_id,
                    "content": [{"type": "text", "text": "done"}],
                },
            ],
        },
    ]


@pytest.mark.asyncio
async def test_offload_hint_formats_for_gemini(offload_hint) -> None:
    formatted = await GeminiChatFormatter().format([offload_hint])
    hint_call_id = offload_hint.content[1].id

    assert formatted == [
        {
            "role": "model",
            "parts": [
                {"text": _NOTIFICATION},
                {
                    "function_call": {
                        "id": hint_call_id,
                        "name": "slow_tool",
                        "args": {},
                    },
                },
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": hint_call_id,
                        "name": "slow_tool",
                        "response": {"output": "done"},
                    },
                },
            ],
        },
    ]
