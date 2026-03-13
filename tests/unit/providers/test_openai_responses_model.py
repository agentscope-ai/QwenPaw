# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for OpenAIResponsesChatModel (Responses API with fallback)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from copaw.providers.openai_responses_model import (
    InvalidMessagesTypeError,
    OpenAIResponsesChatModel,
    _get,
    _to_text,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_model(**overrides: Any) -> OpenAIResponsesChatModel:
    defaults: dict[str, Any] = {
        "model_name": "gpt-4o",
        "api_key": "sk-test",
        "stream": False,
        "client_type": "openai",
        "client_kwargs": {},
        "generate_kwargs": {},
    }
    defaults.update(overrides)
    return OpenAIResponsesChatModel(**defaults)


def _responses_ok(
    text: str = "Hello",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> SimpleNamespace:
    """Fake Responses API return value."""
    return SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text=text)],
            ),
        ],
        output_text=text,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def _chat_completions_ok(
    text: str = "Hi",
    prompt_tokens: int = 8,
    completion_tokens: int = 4,
) -> SimpleNamespace:
    """Fake Chat Completions API return value."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=None),
            ),
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _patch_client(
    monkeypatch,
    model: OpenAIResponsesChatModel,
    *,
    responses_result=None,
    responses_error: type[Exception] | None = None,
    chat_result=None,
) -> dict[str, list]:
    """Monkeypatch model.client and capture calls."""
    captured: dict[str, list] = {"responses": [], "chat": []}

    class FakeResponses:
        async def create(self, **kwargs):
            captured["responses"].append(kwargs)
            if responses_error is not None:
                raise responses_error("boom")
            return responses_result or _responses_ok()

    class FakeChat:
        async def create(self, **kwargs):
            captured["chat"].append(kwargs)
            return chat_result or _chat_completions_ok()

    fake_client = SimpleNamespace(
        responses=FakeResponses(),
        chat=SimpleNamespace(completions=FakeChat()),
    )
    monkeypatch.setattr(model, "client", fake_client)
    return captured


# ------------------------------------------------------------------
# Unit helpers: _get, _to_text
# ------------------------------------------------------------------


def test_get_dict():
    assert _get({"a": 1}, "a") == 1
    assert _get({"a": 1}, "b", 42) == 42


def test_get_object():
    obj = SimpleNamespace(x=10)
    assert _get(obj, "x") == 10
    assert _get(obj, "y", "default") == "default"


def test_to_text_various_types():
    assert _to_text(None) == ""
    assert _to_text("hello") == "hello"
    assert _to_text(42) == "42"
    assert _to_text(3.14) == "3.14"
    assert _to_text(True) == "True"
    assert _to_text([1, 2]) == ""


# ------------------------------------------------------------------
# InvalidMessagesTypeError
# ------------------------------------------------------------------


def test_invalid_messages_type_error():
    err = InvalidMessagesTypeError(str)
    assert "list" in str(err)
    assert "str" in str(err)
    assert isinstance(err, TypeError)


# ------------------------------------------------------------------
# __call__
# ------------------------------------------------------------------


async def test_call_raises_on_non_list_messages():
    model = _make_model()
    with pytest.raises(InvalidMessagesTypeError):
        await model(messages="not a list")


async def test_call_responses_success(monkeypatch) -> None:
    model = _make_model()
    captured = _patch_client(monkeypatch, model)

    response = await model(messages=[{"role": "user", "content": "Hi"}])

    assert len(captured["responses"]) == 1
    assert not captured["chat"]
    assert captured["responses"][0]["model"] == "gpt-4o"
    assert response.content[0]["text"] == "Hello"
    assert response.usage is not None
    assert response.usage.input_tokens == 10


async def test_call_fallback_to_chat_on_api_error(monkeypatch) -> None:
    model = _make_model()
    monkeypatch.setattr(
        model,
        "_responses_fallback_errors",
        (RuntimeError,),
    )
    captured = _patch_client(
        monkeypatch,
        model,
        responses_error=RuntimeError,
    )

    response = await model(messages=[{"role": "user", "content": "Hi"}])

    assert len(captured["responses"]) == 1
    assert len(captured["chat"]) == 1
    assert response.content[0]["text"] == "Hi"


async def test_call_reraises_when_structured_model(monkeypatch) -> None:
    model = _make_model()
    monkeypatch.setattr(
        model,
        "_responses_fallback_errors",
        (RuntimeError,),
    )
    _patch_client(
        monkeypatch,
        model,
        responses_error=RuntimeError,
    )

    from pydantic import BaseModel

    class FakeSchema(BaseModel):
        answer: str

    with pytest.raises(RuntimeError):
        await model(
            messages=[{"role": "user", "content": "Hi"}],
            structured_model=FakeSchema,
        )


async def test_call_stream_wraps_in_generator(monkeypatch) -> None:
    model = _make_model(stream=True)
    _patch_client(monkeypatch, model)

    result = await model(messages=[{"role": "user", "content": "Hi"}])

    chunks = [c async for c in result]
    assert len(chunks) == 1
    assert chunks[0].content[0]["text"] == "Hello"


# ------------------------------------------------------------------
# _call_responses
# ------------------------------------------------------------------


async def test_responses_includes_reasoning_effort(monkeypatch) -> None:
    model = _make_model(reasoning_effort="high")
    captured = _patch_client(monkeypatch, model)

    await model(messages=[{"role": "user", "content": "Think"}])

    req = captured["responses"][0]
    assert req["reasoning"] == {"effort": "high"}


async def test_responses_includes_tools(monkeypatch) -> None:
    model = _make_model()
    captured = _patch_client(monkeypatch, model)

    tools = [{"type": "function", "function": {"name": "fn1"}}]
    await model(
        messages=[{"role": "user", "content": "go"}],
        tools=tools,
        tool_choice="auto",
    )

    req = captured["responses"][0]
    assert req["tools"] == tools
    assert req["tool_choice"] == "auto"


async def test_responses_structured_model(monkeypatch) -> None:
    model = _make_model()
    captured = _patch_client(monkeypatch, model)

    from pydantic import BaseModel

    class MyOutput(BaseModel):
        name: str

    await model(
        messages=[{"role": "user", "content": "Who?"}],
        structured_model=MyOutput,
    )

    req = captured["responses"][0]
    text_format = req["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "MyOutput"
    assert "properties" in text_format["schema"]
    assert text_format["strict"] is True


# ------------------------------------------------------------------
# _call_chat_completions
# ------------------------------------------------------------------


async def test_chat_completions_parses_tool_calls(monkeypatch) -> None:
    model = _make_model()

    tool_call_resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="search",
                                arguments='{"q": "test"}',
                            ),
                        ),
                    ],
                ),
            ),
        ],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )

    _patch_client(monkeypatch, model, chat_result=tool_call_resp)
    monkeypatch.setattr(
        model,
        "_responses_fallback_errors",
        (RuntimeError,),
    )

    class FakeResponses:
        async def create(self, **kwargs):
            raise RuntimeError("force fallback")

    monkeypatch.setattr(model.client, "responses", FakeResponses())

    response = await model(messages=[{"role": "user", "content": "search"}])

    tool_blocks = [b for b in response.content if b["type"] == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0]["name"] == "search"
    assert tool_blocks[0]["input"] == {"q": "test"}


# ------------------------------------------------------------------
# _messages_to_input
# ------------------------------------------------------------------


def test_messages_to_input_valid_roles():
    model = _make_model()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
        {"role": "developer", "content": "dev"},
    ]
    result = model._messages_to_input(messages)

    assert [m["role"] for m in result] == [
        "system",
        "user",
        "assistant",
        "developer",
    ]


def test_messages_to_input_coerces_unknown_role():
    model = _make_model()
    messages = [{"role": "custom_role", "content": "text"}]
    result = model._messages_to_input(messages)

    assert result[0]["role"] == "user"


def test_messages_to_input_converts_tool_to_function_call_output():
    model = _make_model()
    messages = [{"role": "tool", "content": "42", "tool_call_id": "call_1"}]
    result = model._messages_to_input(messages)

    assert len(result) == 1
    assert result[0]["type"] == "function_call_output"
    assert result[0]["output"] == "42"
    assert result[0]["call_id"] == "call_1"


def test_messages_to_input_tool_without_call_id():
    model = _make_model()
    messages = [{"role": "tool", "content": "ok"}]
    result = model._messages_to_input(messages)

    assert result[0]["type"] == "function_call_output"
    assert result[0]["output"] == "ok"
    assert "call_id" not in result[0]


# ------------------------------------------------------------------
# _messages_to_chat
# ------------------------------------------------------------------


def test_messages_to_chat_valid_roles():
    model = _make_model()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "content": "result", "tool_call_id": "call_1"},
        {"role": "developer", "content": "dev"},
    ]
    result = model._messages_to_chat(messages)

    assert [m["role"] for m in result] == [
        "system",
        "user",
        "assistant",
        "tool",
        "developer",
    ]


def test_messages_to_chat_preserves_tool_call_id():
    model = _make_model()
    messages = [
        {"role": "tool", "content": "out", "tool_call_id": "call_abc"},
    ]
    result = model._messages_to_chat(messages)

    assert result[0]["tool_call_id"] == "call_abc"


def test_messages_to_chat_coerces_unknown_role():
    model = _make_model()
    messages = [{"role": "observer", "content": "text"}]
    result = model._messages_to_chat(messages)

    assert result[0]["role"] == "user"


# ------------------------------------------------------------------
# _extract_text
# ------------------------------------------------------------------


def test_extract_text_string():
    model = _make_model()
    assert model._extract_text("hello") == "hello"


def test_extract_text_list_of_blocks():
    model = _make_model()
    content = [
        {"type": "text", "text": "first"},
        {"type": "output_text", "text": "second"},
    ]
    result = model._extract_text(content)
    assert "first" in result
    assert "second" in result


def test_extract_text_list_of_strings():
    model = _make_model()
    assert model._extract_text(["a", "b"]) == "a\nb"


def test_extract_text_dict():
    model = _make_model()
    assert model._extract_text({"text": "val"}) == "val"


def test_extract_text_none():
    model = _make_model()
    assert model._extract_text(None) == ""


# ------------------------------------------------------------------
# _parse_responses
# ------------------------------------------------------------------


def test_parse_responses_text():
    model = _make_model()
    raw = _responses_ok("world")
    result = model._parse_responses(datetime.now(), raw)

    assert result.content[0]["text"] == "world"
    assert result.usage is not None
    assert result.usage.input_tokens == 10


def test_parse_responses_tool_calls():
    model = _make_model()
    raw = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="fc_1",
                name="get_weather",
                arguments='{"city": "Tokyo"}',
            ),
        ],
        output_text="",
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )

    result = model._parse_responses(datetime.now(), raw)

    tool_blocks = [b for b in result.content if b["type"] == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0]["name"] == "get_weather"
    assert tool_blocks[0]["input"] == {"city": "Tokyo"}


def test_parse_responses_empty_output():
    model = _make_model()
    raw = SimpleNamespace(output=[], output_text="", usage=None)
    result = model._parse_responses(datetime.now(), raw)

    assert len(result.content) == 1
    assert result.content[0]["text"] == ""
    assert result.usage is None


def test_parse_responses_output_text_fallback():
    model = _make_model()
    raw = SimpleNamespace(
        output=[],
        output_text="fallback text",
        usage=None,
    )
    result = model._parse_responses(datetime.now(), raw)

    assert result.content[0]["text"] == "fallback text"


# ------------------------------------------------------------------
# Tool choice formatting
# ------------------------------------------------------------------


def test_format_responses_tool_choice_builtins():
    model = _make_model()
    for mode in ("auto", "none", "required"):
        assert model._format_responses_tool_choice(mode) == mode


def test_format_responses_tool_choice_named():
    model = _make_model()
    result = model._format_responses_tool_choice("my_func")
    assert result == {"type": "function", "name": "my_func"}


def test_format_chat_tool_choice_builtins():
    model = _make_model()
    for mode in ("auto", "none", "required"):
        assert model._format_chat_tool_choice(mode) == mode


def test_format_chat_tool_choice_named():
    model = _make_model()
    result = model._format_chat_tool_choice("my_func")
    assert result == {"type": "function", "function": {"name": "my_func"}}
