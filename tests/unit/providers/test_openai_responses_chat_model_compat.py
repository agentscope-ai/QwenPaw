# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from copaw.providers.openai_responses_chat_model_compat import (
    OpenAIResponsesChatModelCompat,
)


class _FakeStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _make_model(stream: bool = True) -> OpenAIResponsesChatModelCompat:
    return OpenAIResponsesChatModelCompat(
        model_name="gpt-5.4-mini",
        api_key="copilot-token",
        stream=stream,
        stream_tool_parsing=False,
        client_kwargs={"base_url": "https://api.individual.githubcopilot.com"},
    )


async def test_streaming_text_response(monkeypatch) -> None:
    model = _make_model(stream=True)

    async def fake_create(**kwargs):
        assert kwargs["stream"] is True
        return _FakeStream(
            [
                SimpleNamespace(
                    type="response.output_item.added",
                    item=SimpleNamespace(
                        type="message", id="msg-1", content=[]
                    ),
                    output_index=0,
                ),
                SimpleNamespace(
                    type="response.output_text.delta",
                    item_id="msg-1",
                    output_index=0,
                    delta="Hel",
                ),
                SimpleNamespace(
                    type="response.output_text.delta",
                    item_id="msg-1",
                    output_index=0,
                    delta="lo",
                ),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(
                        output=[
                            SimpleNamespace(
                                type="message",
                                id="msg-1",
                                content=[
                                    SimpleNamespace(
                                        type="output_text", text="Hello"
                                    ),
                                ],
                            ),
                        ],
                        usage=SimpleNamespace(input_tokens=3, output_tokens=5),
                    ),
                ),
            ],
        )

    monkeypatch.setattr(
        model.client.responses,
        "create",
        fake_create,
    )

    result = await model(messages=[{"role": "user", "content": "hi"}])
    chunks = [chunk async for chunk in result]

    assert [chunk.content[0]["text"] for chunk in chunks[:-1]] == [
        "Hel",
        "Hello",
    ]
    assert chunks[-1].content[0]["text"] == "Hello"
    assert chunks[-1].usage.input_tokens == 3
    assert chunks[-1].usage.output_tokens == 5


async def test_streaming_function_call_finalizes_arguments(
    monkeypatch,
) -> None:
    model = _make_model(stream=True)

    async def fake_create(**kwargs):
        assert kwargs["stream"] is True
        return _FakeStream(
            [
                SimpleNamespace(
                    type="response.output_item.added",
                    item=SimpleNamespace(
                        type="function_call",
                        id="fc-1",
                        call_id="call-1",
                        name="demo_tool",
                        arguments="",
                    ),
                    output_index=0,
                ),
                SimpleNamespace(
                    type="response.function_call_arguments.delta",
                    item_id="fc-1",
                    output_index=0,
                    delta='{"value":',
                ),
                SimpleNamespace(
                    type="response.function_call_arguments.done",
                    item_id="fc-1",
                    output_index=0,
                    name="demo_tool",
                    arguments='{"value":1}',
                ),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(
                        output=[
                            SimpleNamespace(
                                type="function_call",
                                id="fc-1",
                                call_id="call-1",
                                name="demo_tool",
                                arguments='{"value":1}',
                            ),
                        ],
                        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
                    ),
                ),
            ],
        )

    monkeypatch.setattr(
        model.client.responses,
        "create",
        fake_create,
    )

    result = await model(messages=[{"role": "user", "content": "hi"}])
    chunks = [chunk async for chunk in result]

    assert chunks[1].content[0]["type"] == "tool_use"
    assert chunks[1].content[0]["input"] == {}
    assert chunks[1].content[0]["raw_input"] == '{"value":'
    assert chunks[-1].content[0]["input"] == {"value": 1}
    assert chunks[-1].usage.output_tokens == 1


async def test_assistant_history_message_omits_synthetic_id(
    monkeypatch,
) -> None:
    model = _make_model(stream=False)
    captured: dict[str, object] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    id="msg-99",
                    content=[SimpleNamespace(type="output_text", text="ok")],
                ),
            ],
            usage=SimpleNamespace(input_tokens=4, output_tokens=1),
        )

    monkeypatch.setattr(model.client.responses, "create", fake_create)

    response = await model(
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "previous answer"},
        ],
    )

    assert response.content[0]["text"] == "ok"
    assistant_input = captured["input"][1]
    assert assistant_input["type"] == "message"
    assert assistant_input["role"] == "assistant"
    assert assistant_input["content"] == "previous answer"
    assert "id" not in assistant_input


async def test_tools_are_formatted_for_responses_api(monkeypatch) -> None:
    model = _make_model(stream=False)
    captured: dict[str, object] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    id="msg-100",
                    content=[SimpleNamespace(type="output_text", text="ok")],
                ),
            ],
            usage=SimpleNamespace(input_tokens=5, output_tokens=1),
        )

    monkeypatch.setattr(model.client.responses, "create", fake_create)

    await model(
        messages=[{"role": "user", "content": "call tool"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "demo_tool",
                    "description": "Demo tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                        },
                    },
                    "strict": False,
                },
            },
        ],
    )

    assert captured["tools"] == [
        {
            "type": "function",
            "name": "demo_tool",
            "description": "Demo tool",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": ["string", "null"]},
                },
                "required": ["value"],
                "additionalProperties": False,
            },
            "strict": False,
        },
    ]


def test_tools_schema_disallows_additional_properties_recursively() -> None:
    formatted = OpenAIResponsesChatModelCompat._format_responses_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "options": {
                                "type": "object",
                                "properties": {
                                    "cwd": {"type": "string"},
                                },
                            },
                            "steps": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "command": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        ],
    )

    parameters = formatted[0]["parameters"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["options"]["additionalProperties"] is False
    assert (
        parameters["properties"]["steps"]["items"]["additionalProperties"]
        is False
    )


def test_tools_schema_removes_unsupported_path_format() -> None:
    formatted = OpenAIResponsesChatModelCompat._format_responses_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cwd": {
                                "anyOf": [
                                    {"type": "string", "format": "path"},
                                    {"type": "null"},
                                ],
                            },
                        },
                    },
                },
            },
        ],
    )

    cwd_schema = formatted[0]["parameters"]["properties"]["cwd"]["anyOf"][0]
    assert cwd_schema == {"type": "string"}


def test_tools_schema_matches_official_strict_mode_requirements() -> None:
    formatted = OpenAIResponsesChatModelCompat._format_responses_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "title": "ExecuteShellCommandArgs",
                        "properties": {
                            "command": {
                                "type": "string",
                                "title": "Command",
                            },
                            "timeout": {
                                "type": "integer",
                                "default": 60,
                                "title": "Timeout",
                            },
                            "cwd": {
                                "anyOf": [
                                    {
                                        "type": "string",
                                        "format": "path",
                                        "title": "CwdPath",
                                    },
                                    {"type": "null"},
                                ],
                                "default": None,
                                "title": "Cwd",
                            },
                            "note": {
                                "type": "string",
                                "title": "Note",
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
        ],
    )

    parameters = formatted[0]["parameters"]

    assert parameters["required"] == ["command", "timeout", "cwd", "note"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["command"] == {"type": "string"}
    assert parameters["properties"]["timeout"] == {"type": "integer"}
    assert parameters["properties"]["cwd"] == {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ],
    }
    assert parameters["properties"]["note"] == {"type": ["string", "null"]}
