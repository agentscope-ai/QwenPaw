# -*- coding: utf-8 -*-
"""Regression tests for Responses API streams that skip content deltas.

Some providers do not emit ``response.output_text.delta`` /
``response.function_call_arguments.delta`` events and deliver the complete
output only in the terminal ``response.completed`` event.  AgentScope's
stream parser reads assistant text and tool calls from deltas only, so
those turns used to come back as an empty assistant message (issue #8162).

The fake stream mirrors the shape of the OpenAI SDK event objects.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from agentscope.credential import OpenAICredential
from openai.types.responses.response_reasoning_item import (
    ResponseReasoningItem,
    Summary,
)

from qwenpaw.providers.openai_response_provider import (
    OpenAIResponseModelCompat,
)


class _FakeEventStream:
    """Minimal async stream matching the SDK event-stream contract."""

    def __init__(self, items: list[Any], headers: dict | None = None) -> None:
        self._items = items
        self._iterator: Any = None
        self.response = SimpleNamespace(headers=headers or {})

    async def __aenter__(self) -> "_FakeEventStream":
        self._iterator = iter(self._items)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def __aiter__(self) -> "_FakeEventStream":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _StreamHarnessModel(OpenAIResponseModelCompat):
    """Replay a canned event stream through the compat parser."""

    async def _call_api(
        self,
        model_name: str,
        messages: Any,
        tools: Any = None,
        tool_choice: Any = None,
        **_kwargs: Any,
    ) -> Any:
        return self._parse_stream_response(
            datetime.now(),
            self._test_stream,
        )


def _make_stream_model(stream: Any) -> _StreamHarnessModel:
    model = _StreamHarnessModel(
        credential=OpenAICredential(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        ),
        model="gpt-5",
        stream=True,
    )
    object.__setattr__(model, "_test_stream", stream)
    return model


def _completed_response(
    *,
    reasoning: str = "",
    text: str = "",
    tool_calls: tuple[tuple[str, str, str], ...] = (),
) -> Any:
    """Build the ``response`` payload of a terminal event."""
    output: list[Any] = []
    if reasoning:
        output.append(
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[Summary(type="summary_text", text=reasoning)],
            ),
        )
    if text:
        output.append(
            SimpleNamespace(
                type="message",
                id="msg_1",
                content=[SimpleNamespace(type="output_text", text=text)],
            ),
        )
    for index, (call_id, name, arguments) in enumerate(tool_calls):
        output.append(
            SimpleNamespace(
                type="function_call",
                id=f"fc_{index}",
                call_id=call_id,
                name=name,
                arguments=arguments,
            ),
        )
    return SimpleNamespace(
        id="resp_1",
        usage=SimpleNamespace(
            input_tokens=11,
            output_tokens=7,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
        output=output,
    )


def _completed_event(response: Any) -> Any:
    return SimpleNamespace(type="response.completed", response=response)


def _text_delta(text: str) -> Any:
    return SimpleNamespace(
        type="response.output_text.delta",
        item_id="msg_1",
        delta=text,
    )


async def _collect(
    stream: list[Any],
    headers: dict | None = None,
) -> list[Any]:
    model = _make_stream_model(_FakeEventStream(stream, headers))
    response = await model(messages=[])
    return [chunk async for chunk in response]


async def test_completed_only_stream_recovers_the_full_output() -> None:
    """Terminal-event output survives, in response.output order."""
    chunks = await _collect(
        [
            _completed_event(
                _completed_response(
                    reasoning="weighing options",
                    text="Hello there",
                    tool_calls=(("call_1", "get_time", '{"tz":"UTC"}'),),
                ),
            ),
        ],
        headers={"x-ds-cache-status": "HIT"},
    )

    final = chunks[-1]
    assert final.is_last
    assert [block.type for block in final.content] == [
        "thinking",
        "text",
        "tool_call",
    ]
    assert final.content[1].text == "Hello there"
    assert final.content[2].name == "get_time"
    assert final.content[2].input == '{"tz":"UTC"}'
    assert final.usage is not None
    assert final.usage.input_tokens == 11
    assert final.usage.metadata["provider_cache_status"] == "HIT"


async def test_delta_stream_is_not_duplicated_by_the_completed_event() -> None:
    """Normal delta streaming must stay byte-identical."""
    chunks = await _collect(
        [
            _text_delta("Hel"),
            _text_delta("lo"),
            _completed_event(_completed_response(text="Hello")),
        ],
    )

    final = chunks[-1]
    assert final.is_last
    text_blocks = [b for b in final.content if b.type == "text"]
    assert [b.text for b in text_blocks] == ["Hello"]


async def test_completed_only_stream_without_content_stays_empty() -> None:
    """A genuinely empty terminal event is not turned into fake content."""
    chunks = await _collect([_completed_event(_completed_response())])

    final = chunks[-1]
    assert final.is_last
    assert final.content == []
