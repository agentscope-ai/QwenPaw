# -*- coding: utf-8 -*-
from __future__ import annotations

from agentscope_runtime.engine.schemas.agent_schemas import Message

from copaw.app.runner.api import (
    _compact_chat_history_messages,
    _paginate_chat_history_messages,
    _truncate_chat_history_messages,
)


def test_truncate_chat_history_messages_only_for_large_plugin_output() -> None:
    tool_output = "x" * 120
    messages = [
        Message.model_validate(
            {
                "id": "m1",
                "role": "assistant",
                "type": "message",
                "content": [{"type": "text", "text": "hello"}],
            },
        ),
        Message.model_validate(
            {
                "id": "m2",
                "role": "system",
                "type": "plugin_call_output",
                "content": [
                    {
                        "type": "data",
                        "data": {
                            "call_id": "c1",
                            "name": "read_file",
                            "output": tool_output,
                        },
                    },
                ],
            },
        ),
    ]

    result = _truncate_chat_history_messages(
        messages, max_plugin_output_chars=20
    )
    result_dump = [msg.model_dump() for msg in result]

    assert len(result) == 2
    # Normal assistant message should stay untouched.
    assert result_dump[0]["content"][0]["text"] == "hello"

    output = result_dump[1]["content"][0]["data"]["output"]
    assert output.startswith("x" * 20)
    assert "truncated by CoPaw chat API" in output


def test_truncate_chat_history_messages_keeps_small_plugin_output() -> None:
    messages = [
        Message.model_validate(
            {
                "id": "m3",
                "role": "system",
                "type": "plugin_call_output",
                "content": [
                    {
                        "type": "data",
                        "data": {
                            "call_id": "c2",
                            "name": "echo",
                            "output": "small output",
                        },
                    },
                ],
            },
        ),
    ]

    result = _truncate_chat_history_messages(
        messages, max_plugin_output_chars=50
    )
    result_dump = [msg.model_dump() for msg in result]
    output = result_dump[0]["content"][0]["data"]["output"]
    assert output == "small output"


def test_compact_chat_history_messages_filters_tool_trace_only() -> None:
    messages = []
    for i in range(120):
        messages.append(
            Message.model_validate(
                {
                    "id": f"a-{i}",
                    "role": "assistant",
                    "type": "message",
                    "content": [{"type": "text", "text": f"msg-{i}"}],
                },
            ),
        )
        messages.append(
            Message.model_validate(
                {
                    "id": f"t-{i}",
                    "role": "assistant",
                    "type": "plugin_call",
                    "content": [
                        {
                            "type": "data",
                            "data": {
                                "call_id": f"c-{i}",
                                "name": "read_file",
                                "arguments": "{}",
                            },
                        },
                    ],
                },
            ),
        )

    result = _compact_chat_history_messages(messages)

    assert len(result) == 120
    result_dump = [msg.model_dump() for msg in result]
    assert all(item["type"] != "plugin_call" for item in result_dump)
    assert result_dump[0]["id"] == "a-0"
    assert result_dump[-1]["id"] == "a-119"


def test_paginate_chat_history_messages_returns_stable_page_meta() -> None:
    messages = [
        Message.model_validate(
            {
                "id": f"m-{i}",
                "role": "assistant",
                "type": "message",
                "content": [{"type": "text", "text": f"msg-{i}"}],
            },
        )
        for i in range(10)
    ]

    page, total, has_more = _paginate_chat_history_messages(
        messages, offset=3, limit=4
    )
    page_dump = [msg.model_dump() for msg in page]

    assert total == 10
    assert has_more is True
    assert len(page_dump) == 4
    assert page_dump[0]["id"] == "m-3"
    assert page_dump[-1]["id"] == "m-6"


def test_paginate_chat_history_messages_offset_overflow_returns_empty_page() -> (
    None
):
    messages = [
        Message.model_validate(
            {
                "id": "m-1",
                "role": "assistant",
                "type": "message",
                "content": [{"type": "text", "text": "hello"}],
            },
        ),
    ]

    page, total, has_more = _paginate_chat_history_messages(
        messages, offset=5, limit=10
    )

    assert page == []
    assert total == 1
    assert has_more is False
