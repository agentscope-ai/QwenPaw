# -*- coding: utf-8 -*-
from __future__ import annotations

from agentscope_runtime.engine.schemas.agent_schemas import Message

from copaw.app.runner.api import (
    _compact_chat_history_messages,
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

    result = _truncate_chat_history_messages(messages, max_plugin_output_chars=20)
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

    result = _truncate_chat_history_messages(messages, max_plugin_output_chars=50)
    result_dump = [msg.model_dump() for msg in result]
    output = result_dump[0]["content"][0]["data"]["output"]
    assert output == "small output"


def test_compact_chat_history_messages_filters_tool_trace_and_caps_count() -> None:
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

    result = _compact_chat_history_messages(messages, max_history_messages=80)

    assert len(result) == 80
    result_dump = [msg.model_dump() for msg in result]
    assert all(item["type"] != "plugin_call" for item in result_dump)
    assert result_dump[0]["id"] == "a-40"
    assert result_dump[-1]["id"] == "a-119"
