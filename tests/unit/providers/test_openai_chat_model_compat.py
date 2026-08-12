# -*- coding: utf-8 -*-
"""Tests for schema-guided tool-call input coercion (issue #6839).

Models sometimes emit unquoted numbers or booleans for string-typed tool
parameters (e.g. ``"assetInfo": 1.000001`` where the schema declares
``type: string``).  ``jsonschema.validate`` rejects those values, so the
tool call always fails.  The compat layer coerces declared ``string``
fields back to strings before agentscope validates the input.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from agentscope.credential import OpenAICredential
from agentscope.message import ToolCallBlock
from agentscope.model._model_response import ChatResponse

from qwenpaw.providers.openai_chat_model_compat import (
    OpenAIChatModelCompat,
    _coerce_string_fields,
    _coerce_tool_input,
)

STOCK_SCHEMA = {
    "type": "object",
    "required": ["apiKey", "assetInfo"],
    "properties": {
        "apiKey": {"type": "string"},
        "assetInfo": {"type": "string"},
        "count": {"type": "integer", "default": 240},
    },
}


def _make_model() -> OpenAIChatModelCompat:
    return OpenAIChatModelCompat(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Pure coercion helpers
# ---------------------------------------------------------------------------


def test_coerce_tool_input_number_to_string() -> None:
    """The exact issue #6839 case: unquoted float for a string field."""
    raw = '{"apiKey": "k", "assetInfo": 1.000001, "count": 240}'
    out = _coerce_tool_input(raw, STOCK_SCHEMA)
    parsed = json.loads(out)
    assert parsed == {"apiKey": "k", "assetInfo": "1.000001", "count": 240}
    # The integer-typed field keeps its numeric type.
    assert isinstance(parsed["count"], int)
    assert isinstance(parsed["assetInfo"], str)


def test_coerce_tool_input_integer_field_untouched() -> None:
    """Numbers landing in integer/number fields are never coerced."""
    raw = '{"apiKey": "k", "assetInfo": "1.000001", "count": 240}'
    out = _coerce_tool_input(raw, STOCK_SCHEMA)
    assert out == raw  # byte-identical no-op


def test_coerce_tool_input_bool_to_json_literal() -> None:
    schema = {
        "type": "object",
        "properties": {"flag": {"type": "string"}},
    }
    assert json.loads(_coerce_tool_input('{"flag": true}', schema)) == {
        "flag": "true",
    }
    assert json.loads(_coerce_tool_input('{"flag": false}', schema)) == {
        "flag": "false",
    }


def test_coerce_tool_input_invalid_json_passthrough() -> None:
    """Broken JSON is left to agentscope's existing json-repair path."""
    broken = '{"apiKey": "k", "assetInfo": 1.000001, "count": 240'
    assert _coerce_tool_input(broken, STOCK_SCHEMA) == broken


def test_coerce_tool_input_no_schema_passthrough() -> None:
    raw = '{"assetInfo": 1.000001}'
    assert _coerce_tool_input(raw, None) == raw


def test_coerce_tool_input_non_dict_passthrough() -> None:
    raw = "[1, 2, 3]"
    assert _coerce_tool_input(raw, STOCK_SCHEMA) == raw


def test_coerce_string_fields_unknown_property_untouched() -> None:
    """Fields absent from schema properties are never touched."""
    parsed = {"mystery": 42, "assetInfo": 1.5}
    out = _coerce_string_fields(dict(parsed), STOCK_SCHEMA)
    assert out["mystery"] == 42
    assert out["assetInfo"] == "1.5"


# ---------------------------------------------------------------------------
# Schema capture in _format_tools
# ---------------------------------------------------------------------------


def test_format_tools_captures_tool_schemas() -> None:
    model = _make_model()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "stock-client-local__analyze",
                "description": "fetch K-line data",
                "parameters": STOCK_SCHEMA,
            },
        },
    ]
    formatted, _ = model._format_tools(tools, None)
    assert formatted is not None
    assert model._tool_schemas == {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }


def test_format_tools_without_tools_clears_mapping() -> None:
    model = _make_model()
    model._tool_schemas = {"stale": {"type": "object"}}
    model._format_tools(None, None)
    assert model._tool_schemas == {}


# ---------------------------------------------------------------------------
# End-to-end: streaming path (final accumulated chunk)
# ---------------------------------------------------------------------------


class _CoercionHarnessModel(OpenAIChatModelCompat):
    async def _call_api(self, *args: Any, **kwargs: Any) -> Any:
        stream = getattr(self, "_test_stream", None)
        if stream is not None:
            return self._parse_stream_response(datetime.now(), stream)
        non_stream = getattr(self, "_test_non_stream", None)
        if non_stream is not None:
            return non_stream
        return await super()._call_api(*args, **kwargs)


def _make_chunk(tool_calls: list[Any] | None = None) -> Any:
    delta = SimpleNamespace(
        reasoning_content=None,
        content=None,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(usage=None, choices=[choice])


async def test_stream_coercion_on_accumulated_final_chunk() -> None:
    model = _CoercionHarnessModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=True,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "stock-client-local__analyze",
                "description": "fetch K-line data",
                "parameters": STOCK_SCHEMA,
            },
        },
    ]
    # Seed the schema mapping exactly like the real _call_api flow does.
    model._format_tools(tools, None)

    # The model emits the arguments split over deltas, with an unquoted
    # number for the string-typed assetInfo field (issue #6839).
    stream_items = [
        _make_chunk(
            [
                SimpleNamespace(
                    index=0,
                    id="call_1",
                    function=SimpleNamespace(
                        name="stock-client-local__analyze",
                        arguments='{"apiKey": "k", "asset',
                    ),
                ),
            ],
        ),
        _make_chunk(
            [
                SimpleNamespace(
                    index=0,
                    id=None,
                    function=SimpleNamespace(
                        name=None,
                        arguments='Info": 1.000001, "count": 240}',
                    ),
                ),
            ],
        ),
    ]

    class _FakeAsyncStream:
        def __init__(self, items: list[Any]) -> None:
            self._iter = iter(items)

        async def __aenter__(self) -> "_FakeAsyncStream":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        def __aiter__(self) -> "_FakeAsyncStream":
            return self

        async def __anext__(self) -> Any:
            try:
                return next(self._iter)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    object.__setattr__(model, "_test_stream", _FakeAsyncStream(stream_items))
    try:
        response = await model(messages=[])
        chunks = [chunk async for chunk in response]
    finally:
        object.__delattr__(model, "_test_stream")

    final = chunks[-1]
    assert final.is_last
    tool_blocks = [
        block
        for block in final.content
        if getattr(block, "type", None) in ("tool_call", "tool_use")
    ]
    assert len(tool_blocks) == 1
    parsed = json.loads(tool_blocks[0].input)
    assert parsed["assetInfo"] == "1.000001"
    assert parsed["count"] == 240


async def test_non_stream_coercion() -> None:
    model = _CoercionHarnessModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="dummy",
        stream=False,
    )
    model._tool_schemas = {"stock-client-local__analyze": STOCK_SCHEMA}

    object.__setattr__(
        model,
        "_test_non_stream",
        ChatResponse(
            content=[
                ToolCallBlock(
                    id="call_1",
                    name="stock-client-local__analyze",
                    input='{"apiKey": "k", "assetInfo": 1.000001}',
                ),
            ],
            is_last=True,
        ),
    )
    try:
        response = await model(messages=[])
    finally:
        object.__delattr__(model, "_test_non_stream")

    assert isinstance(response, ChatResponse)
    parsed = json.loads(response.content[0].input)
    assert parsed["assetInfo"] == "1.000001"
