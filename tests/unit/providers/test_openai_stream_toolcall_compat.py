# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.credential import OpenAICredential
from agentscope.message import ToolCallBlock
from agentscope.model._model_response import ChatResponse

from qwenpaw.providers.openai_chat_model_compat import (
    OpenAIChatModelCompat,
    _sanitize_tool_call,
)
from qwenpaw.utils.tool_call_extra import collect_transient_tool_call_extras


class CompatHarnessOpenAIChatModel(OpenAIChatModelCompat):
    async def _call_api(self, *args: Any, **kwargs: Any) -> Any:
        stream = getattr(self, "_test_stream", None)
        if stream is not None:
            return self._parse_stream_response(datetime.now(), stream)
        return await super()._call_api(*args, **kwargs)

    async def parse_stream_for_test(
        self,
        start_datetime: datetime,
        stream: Any,
    ) -> list[Any]:
        responses = []
        async for response in self._parse_stream_response(
            start_datetime,
            stream,
        ):
            responses.append(response)
        return responses

    async def call_stream_for_test(self, stream: Any) -> list[Any]:
        object.__setattr__(self, "_test_stream", stream)
        try:
            response = await self(messages=[])
            return [chunk async for chunk in response]
        finally:
            object.__delattr__(self, "_test_stream")

    def relay_stream_for_test(self, response: Any) -> Any:
        """Expose the compatibility relay for lifecycle assertions."""
        return self._relay_stream_tool_call_extras(response)


class FakeAsyncStream:
    def __init__(self, items: list[Any]):
        self._items = items
        self._iter = None

    async def __aenter__(self) -> "FakeAsyncStream":
        self._iter = iter(self._items)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def __aiter__(self) -> "FakeAsyncStream":
        return self

    async def __anext__(self) -> Any:
        assert self._iter is not None
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _make_chunk(
    tool_calls: list[Any] | None = None,
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
) -> Any:
    delta = SimpleNamespace(
        reasoning_content=reasoning_content,
        content=content,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(usage=None, choices=[choice])


async def test_stream_parser_skips_tool_call_without_function() -> None:
    model = CompatHarnessOpenAIChatModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )

    malformed_tool_call = SimpleNamespace(
        index=0,
        id="call_bad",
        function=None,
    )
    none_arguments_tool_call = SimpleNamespace(
        index=1,
        id="call_partial",
        function=SimpleNamespace(name="ping", arguments=None),
    )
    valid_tool_call = SimpleNamespace(
        index=0,
        id="call_ok",
        function=SimpleNamespace(name="ping", arguments='{"x":1}'),
    )

    stream = FakeAsyncStream(
        [
            _make_chunk([malformed_tool_call]),
            _make_chunk([none_arguments_tool_call]),
            _make_chunk([valid_tool_call]),
        ],
    )

    responses = await model.parse_stream_for_test(
        datetime.now(),
        stream,
    )

    assert responses
    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if getattr(block, "type", None) in ("tool_use", "tool_call")
    ]
    assert tool_blocks
    last = tool_blocks[-1]
    assert getattr(last, "name", None) == "ping"
    block_input = getattr(last, "input", None)
    if isinstance(block_input, str):
        block_input = json.loads(block_input)
    assert block_input == {"x": 1}


async def test_stream_parser_carries_extra_content_on_strict_block() -> None:
    """Gemini thought signatures survive strict ToolCallBlock parsing."""
    model = CompatHarnessOpenAIChatModel(
        credential=OpenAICredential(
            id="qwenpaw-example",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )
    tool_call = SimpleNamespace(
        index=0,
        id="call_sig",
        function=SimpleNamespace(name="ping", arguments='{"x":1}'),
        extra_content={"thought_signature": "signature-abc"},
    )

    responses = await model.parse_stream_for_test(
        datetime.now(),
        FakeAsyncStream([_make_chunk([tool_call])]),
    )

    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if getattr(block, "type", None) in ("tool_use", "tool_call")
    ]
    assert tool_blocks
    assert not hasattr(tool_blocks[0], "extra_content")
    assert collect_transient_tool_call_extras(tool_blocks) == {
        "call_sig": {
            "provider_id": "example",
            "extra_content": {"thought_signature": "signature-abc"},
        },
    }


@pytest.mark.parametrize("repeat_tool_id", [True, False])
async def test_full_stream_preserves_extra_from_later_chunk(
    repeat_tool_id: bool,
) -> None:
    """The final AgentScope accumulator receives late thought signatures."""
    model = CompatHarnessOpenAIChatModel(
        credential=OpenAICredential(
            id="qwenpaw-credential-name",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        provider_id="configured-name",
        model="dummy",
        stream=True,
    )
    first = SimpleNamespace(
        index=0,
        id="call_sig",
        function=SimpleNamespace(name="ping", arguments='{"x":'),
    )
    second = SimpleNamespace(
        index=0,
        id="call_sig" if repeat_tool_id else None,
        function=SimpleNamespace(name=None, arguments="1}"),
        extra_content={"thought_signature": "signature-late"},
    )

    responses = await model.call_stream_for_test(
        FakeAsyncStream([_make_chunk([first]), _make_chunk([second])]),
    )

    final = responses[-1]
    assert final.is_last
    tool_block = next(
        block
        for block in final.content
        if getattr(block, "type", None) in ("tool_use", "tool_call")
    )
    assert tool_block.input == '{"x":1}'
    assert collect_transient_tool_call_extras([tool_block]) == {
        "call_sig": {
            "provider_id": "configured-name",
            "extra_content": {"thought_signature": "signature-late"},
        },
    }


async def test_stream_relay_closes_inner_generator_immediately() -> None:
    """Closing the public stream promptly releases the provider stream."""
    model = CompatHarnessOpenAIChatModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )
    inner_closed = False

    async def inner_stream():
        nonlocal inner_closed
        try:
            yield SimpleNamespace(content=[], is_last=False)
            yield SimpleNamespace(content=[], is_last=True)
        finally:
            inner_closed = True

    response = inner_stream()
    relay = model.relay_stream_for_test(response)
    await anext(relay)
    await relay.aclose()

    assert inner_closed


def test_sanitize_tool_call_normalizes_non_string_arguments() -> None:
    none_arguments_tool_call = SimpleNamespace(
        index=0,
        id="call_partial",
        function=SimpleNamespace(name="ping", arguments=None),
    )
    non_string_arguments_tool_call = SimpleNamespace(
        index=1,
        id="call_dict",
        function=SimpleNamespace(name="ping", arguments={"x": 2}),
    )
    missing_arguments_tool_call = SimpleNamespace(
        index=2,
        id="call_missing_args",
        function=SimpleNamespace(name="ping"),
    )
    missing_name_tool_call = SimpleNamespace(
        index=3,
        id="call_missing_name",
        function=SimpleNamespace(arguments={"x": 3}),
    )
    missing_name_and_arguments_tool_call = SimpleNamespace(
        index=4,
        id="call_missing_both",
        function=SimpleNamespace(),
    )

    sanitized_none_arguments = _sanitize_tool_call(none_arguments_tool_call)
    assert sanitized_none_arguments is not None
    assert sanitized_none_arguments.function.name == "ping"
    assert sanitized_none_arguments.function.arguments == ""

    sanitized_non_string_arguments = _sanitize_tool_call(
        non_string_arguments_tool_call,
    )
    assert sanitized_non_string_arguments is not None
    assert sanitized_non_string_arguments.function.name == "ping"
    assert isinstance(sanitized_non_string_arguments.function.arguments, str)
    assert json.loads(sanitized_non_string_arguments.function.arguments) == {
        "x": 2,
    }

    sanitized_missing_arguments = _sanitize_tool_call(
        missing_arguments_tool_call,
    )
    assert sanitized_missing_arguments is not None
    assert sanitized_missing_arguments.function.name == "ping"
    assert sanitized_missing_arguments.function.arguments == ""

    sanitized_missing_name = _sanitize_tool_call(missing_name_tool_call)
    assert sanitized_missing_name is not None
    assert sanitized_missing_name.function.name == ""
    assert isinstance(sanitized_missing_name.function.arguments, str)
    assert json.loads(sanitized_missing_name.function.arguments) == {"x": 3}

    sanitized_missing_name_and_arguments = _sanitize_tool_call(
        missing_name_and_arguments_tool_call,
    )
    assert sanitized_missing_name_and_arguments is not None
    assert sanitized_missing_name_and_arguments.function.name == ""
    assert sanitized_missing_name_and_arguments.function.arguments == ""


@pytest.mark.parametrize(
    ("use_reasoning", "id_prefix"),
    [
        (False, "text_call_"),
        (True, "think_call_"),
    ],
)
async def test_tagged_tool_calls_use_agentscope_blocks_once(
    use_reasoning: bool,
    id_prefix: str,
) -> None:
    model = CompatHarnessOpenAIChatModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )
    tagged = '<tool_call>{"name":"ping","arguments":{"x":1}}</tool_call>'
    if use_reasoning:
        tagged_chunk = _make_chunk(reasoning_content=tagged)
        following_chunk = _make_chunk(reasoning_content="done")
    else:
        tagged_chunk = _make_chunk(content=tagged)
        following_chunk = _make_chunk(content="done")

    responses = await model.parse_stream_for_test(
        datetime.now(),
        FakeAsyncStream([tagged_chunk, following_chunk]),
    )

    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if isinstance(block, ToolCallBlock)
    ]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].id.startswith(id_prefix)
    assert tool_blocks[0].name == "ping"
    assert json.loads(tool_blocks[0].input) == {"x": 1}

    accumulated = ChatResponse(content=[], is_last=True)
    for response in responses:
        accumulated.append_chat_response(response)

    accumulated_tools = [
        block
        for block in accumulated.content
        if isinstance(block, ToolCallBlock)
    ]
    assert len(accumulated_tools) == 1
    assert json.loads(accumulated_tools[0].input) == {"x": 1}


async def test_multiple_tagged_tool_calls_have_unique_ids() -> None:
    model = CompatHarnessOpenAIChatModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )
    tagged = (
        '<tool_call>{"name":"first","arguments":{}}</tool_call>'
        '<tool_call>{"name":"second","arguments":{}}</tool_call>'
    )

    responses = await model.parse_stream_for_test(
        datetime.now(),
        FakeAsyncStream([_make_chunk(content=tagged)]),
    )

    tool_blocks = [
        block
        for response in responses
        for block in response.content
        if isinstance(block, ToolCallBlock)
    ]
    assert [block.name for block in tool_blocks] == ["first", "second"]
    assert len({block.id for block in tool_blocks}) == 2
