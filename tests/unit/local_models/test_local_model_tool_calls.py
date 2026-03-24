from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from copaw.local_models.backends.base import LocalBackend
from copaw.local_models.chat_model import LocalChatModel
from copaw.local_models.tag_parser import parse_tool_calls_from_text


class DummyLocalBackend(LocalBackend):
    def __init__(
        self,
        model_path: str = "",
        *,
        stream_chunks: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> None:
        self._stream_chunks = stream_chunks or []
        self._loaded = True

    def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        structured_model: Any = None,
        **kwargs: Any,
    ) -> dict:
        return {"choices": [], "usage": None}

    def chat_completion_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        yield from self._stream_chunks

    def unload(self) -> None:
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded


def _make_stream_chunk(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "delta": {
                    "content": None,
                    "reasoning_content": None,
                    "tool_calls": tool_calls,
                },
            },
        ],
    }


def test_parse_tool_calls_from_text_supports_openai_function_format() -> None:
    tool_call = {
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "execute_shell_command",
            "arguments": json.dumps({"command": "ls -la"}),
        },
    }
    text = (
        "prefix\n"
        f"<tool_call>\n{json.dumps(tool_call)}\n</tool_call>\n"
        "suffix"
    )

    parsed = parse_tool_calls_from_text(text)

    assert parsed.text_before == "prefix"
    assert parsed.text_after == "suffix"
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].id == "call_abc123"
    assert parsed.tool_calls[0].name == "execute_shell_command"
    assert parsed.tool_calls[0].arguments == {"command": "ls -la"}
    assert parsed.tool_calls[0].raw_arguments == "{\"command\": \"ls -la\"}"


def test_stream_response_waits_for_non_empty_tool_name() -> None:
    backend = DummyLocalBackend(
        stream_chunks=[
            _make_stream_chunk(
                [
                    {
                        "index": 0,
                        "id": "call_stream",
                        "function": {"arguments": '{"command": '},
                    },
                ],
            ),
            _make_stream_chunk(
                [
                    {
                        "index": 0,
                        "function": {
                            "name": "execute_shell_command",
                            "arguments": '"ls -la"}',
                        },
                    },
                ],
            ),
        ],
    )
    model = LocalChatModel("dummy", backend, stream=True)

    async def _collect_responses() -> list[Any]:
        responses = []
        async for response in model._stream_response(
            messages=[],
            tools=None,
            tool_choice=None,
            start_datetime=datetime.now(),
        ):
            responses.append(response)
        return responses

    responses = asyncio.run(_collect_responses())

    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if block.get("type") == "tool_use"
    ]

    assert tool_blocks
    assert [block["name"] for block in tool_blocks] == ["execute_shell_command"]
    assert tool_blocks[0]["id"] == "call_stream"
    assert tool_blocks[0]["input"] == {"command": "ls -la"}
    assert tool_blocks[0]["raw_input"] == '{"command": "ls -la"}'
