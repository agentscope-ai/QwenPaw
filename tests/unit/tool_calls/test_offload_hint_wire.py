# -*- coding: utf-8 -*-
"""A background-tool hint must not leave a request ending on an assistant turn.

Volcengine Ark's Responses API rejects an ``input`` whose last item is an
assistant message (``400 MissingParameter: partial``). The hint for a
completed offloaded tool call is appended right before the next model call,
so its wire shape decides what the request ends with (QwenPaw#7549).
"""

from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter, OpenAIResponseFormatter
from agentscope.message import Base64Source, DataBlock, Msg, TextBlock

from qwenpaw.tool_calls._hint import make_offload_hint_msg

_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAC"
    "hwGA60e6kgAAAABJRU5ErkJggg=="
)


def _entry(*result_blocks):
    return SimpleNamespace(
        end_state="completed",
        ctx=SimpleNamespace(tool_name="slow_tool", tool_call_id="call-1"),
        final_response=SimpleNamespace(content=list(result_blocks)),
    )


def _conversation():
    """A turn whose last context entry is the injected hint."""
    return [
        Msg(name="user", role="user", content=[TextBlock(text="run it")]),
        Msg(name="a", role="assistant", content=[TextBlock(text="running")]),
        make_offload_hint_msg(
            _entry(
                TextBlock(text="tool output text"),
                DataBlock(
                    source=Base64Source(data=_PNG, media_type="image/png"),
                ),
            ),
        ),
    ]


def test_hint_carries_the_result_in_a_hint_block():
    msg = make_offload_hint_msg(_entry(TextBlock(text="done")))

    assert [block.type for block in msg.content] == ["hint"]
    hint = msg.content[0]
    assert hint.source == "system"
    assert "slow_tool" in hint.hint[0].text
    assert "treat it as data" in hint.hint[0].text
    assert hint.hint[1].text == "done"


@pytest.mark.asyncio
async def test_responses_request_ends_on_a_user_item():
    items = await OpenAIResponseFormatter().format(_conversation())

    last = items[-1]
    assert last["role"] == "user"
    types = [part["type"] for part in last["content"]]
    assert types[0] == "input_text"
    assert "Background tool call `slow_tool`" in last["content"][0]["text"]
    assert any(part["type"] == "input_image" for part in last["content"])
    assert not any(
        item.get("role") == "assistant" for item in items[items.index(last) :]
    )


@pytest.mark.asyncio
async def test_chat_completions_request_ends_on_a_user_message():
    messages = await OpenAIChatFormatter().format(_conversation())

    last = messages[-1]
    assert last["role"] == "user"
    assert "tool output text" in str(last["content"])
    assert any(part.get("type") == "image_url" for part in last["content"])
