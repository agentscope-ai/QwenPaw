# -*- coding: utf-8 -*-
import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg

from copaw.agents.model_factory import _create_file_block_support_formatter


def _create_formatter():
    formatter_cls = _create_file_block_support_formatter(OpenAIChatFormatter)
    return formatter_cls()


@pytest.mark.asyncio
async def test_formatter_strips_top_level_name_fields() -> None:
    formatter = _create_formatter()
    msgs = [
        Msg(name="system", role="system", content="sys"),
        Msg(name="user", role="user", content="hello"),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {"type": "text", "text": "calling tool"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                    "raw_input": "{\"path\":\"README.md\"}",
                },
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_result",
                    "id": "call_1",
                    "name": "read_file",
                    "output": "ok",
                },
            ],
        ),
    ]

    payload = await formatter.format(msgs)

    assert payload
    assert all("name" not in message for message in payload)

    assistant_with_tool_call = next(
        message for message in payload if message.get("tool_calls")
    )
    assert (
        assistant_with_tool_call["tool_calls"][0]["function"]["name"]
        == "read_file"
    )

    tool_message = next(
        message for message in payload if message.get("role") == "tool"
    )
    assert "name" not in tool_message


@pytest.mark.asyncio
async def test_formatter_handles_follow_up_turn_without_name_field() -> None:
    formatter = _create_formatter()
    msgs = [
        Msg(name="system", role="system", content="sys"),
        Msg(name="user", role="user", content="first"),
        Msg(name="assistant", role="assistant", content="first reply"),
        Msg(name="user", role="user", content="second"),
    ]

    payload = await formatter.format(msgs)

    assert payload
    assert all("name" not in message for message in payload)
