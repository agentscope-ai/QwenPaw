# -*- coding: utf-8 -*-
"""Verify fix for #155: thinking blocks preserved as reasoning_content."""
import asyncio
import json

from agentscope.message import (
    Msg,
    ThinkingBlock,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from agentscope.model import OpenAIChatModel

from copaw.agents.model_factory import _create_formatter_instance


def test_reasoning_content_preserved():
    """Thinking blocks must appear as reasoning_content in formatted output."""
    formatter = _create_formatter_instance(OpenAIChatModel)

    msgs = [
        Msg(
            name="system",
            role="system",
            content="You are a helpful assistant.",
        ),
        Msg(name="user", role="user", content="What time is it now?"),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ThinkingBlock(
                    type="thinking",
                    thinking="I should call get_current_time to answer this.",
                ),
                TextBlock(type="text", text="Let me check."),
                ToolUseBlock(
                    type="tool_use",
                    id="call_001",
                    name="get_current_time",
                    input={},
                ),
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
                ToolResultBlock(
                    type="tool_result",
                    id="call_001",
                    name="get_current_time",
                    output="2026-03-01 14:30:00 CST",
                ),
            ],
        ),
    ]

    formatted = asyncio.run(formatter.format(msgs))

    assistant_msgs = [
        m
        for m in formatted
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    assert len(assistant_msgs) == 1, (
        f"Expected 1 assistant msg with tool_calls, "
        f"got {len(assistant_msgs)}. "
        f"All formatted: {json.dumps(formatted, ensure_ascii=False)}"
    )

    msg = assistant_msgs[0]
    reasoning = msg.get("reasoning_content")
    assert reasoning, (
        f"reasoning_content missing! "
        f"Formatted msg: {json.dumps(msg, ensure_ascii=False, indent=2)}"
    )
    assert "get_current_time" in reasoning
    print(f"✅ PASS — reasoning_content preserved: {reasoning}")


def test_no_reasoning_when_no_thinking():
    """Messages without thinking blocks should not get reasoning_content."""
    formatter = _create_formatter_instance(OpenAIChatModel)

    msgs = [
        Msg(name="system", role="system", content="Hi"),
        Msg(name="user", role="user", content="Hello"),
        Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text="Hi there!")],
        ),
    ]

    formatted = asyncio.run(formatter.format(msgs))
    assistant_msgs = [m for m in formatted if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1

    msg = assistant_msgs[0]
    assert (
        "reasoning_content" not in msg
    ), (
        "reasoning_content should not be present "
        "when there are no thinking blocks"
    )
    print("✅ PASS — no reasoning_content when no thinking blocks")


def test_multiple_assistant_messages():
    """Each assistant message gets its own reasoning_content."""
    formatter = _create_formatter_instance(OpenAIChatModel)

    msgs = [
        Msg(name="system", role="system", content="Hi"),
        Msg(name="user", role="user", content="Do two things"),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ThinkingBlock(
                    type="thinking",
                    thinking="First task thinking",
                ),
                TextBlock(type="text", text="Doing first thing."),
                ToolUseBlock(
                    type="tool_use",
                    id="c1",
                    name="tool_a",
                    input={},
                ),
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
                ToolResultBlock(
                    type="tool_result",
                    id="c1",
                    name="tool_a",
                    output="done",
                ),
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ThinkingBlock(
                    type="thinking",
                    thinking="Second task thinking",
                ),
                TextBlock(type="text", text="Doing second thing."),
                ToolUseBlock(
                    type="tool_use",
                    id="c2",
                    name="tool_b",
                    input={},
                ),
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
                ToolResultBlock(
                    type="tool_result",
                    id="c2",
                    name="tool_b",
                    output="done",
                ),
            ],
        ),
    ]

    formatted = asyncio.run(formatter.format(msgs))
    assistant_msgs = [
        m
        for m in formatted
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    assert (
        len(assistant_msgs) == 2
    ), f"Expected 2 assistant msgs, got {len(assistant_msgs)}"

    assert (
        assistant_msgs[0].get("reasoning_content") == "First task thinking"
    )
    assert (
        assistant_msgs[1].get("reasoning_content") == "Second task thinking"
    )
    print(
        "✅ PASS — multiple assistant messages "
        "each get correct reasoning_content"
    )


if __name__ == "__main__":
    test_reasoning_content_preserved()
    test_no_reasoning_when_no_thinking()
    test_multiple_assistant_messages()
    print("\nAll tests passed!")
