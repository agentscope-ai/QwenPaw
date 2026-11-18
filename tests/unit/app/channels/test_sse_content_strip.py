# -*- coding: utf-8 -*-
"""SSE content events must hide scaffolding, not only headlines."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.event import EventType

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import (
    AgentResponse,
    DataContent,
    Message,
    MessageType,
    Role,
    TextContent,
)


class _ContentEvent:
    """Minimal stand-in for a content event as the channel sees it."""

    object = "content"

    def __init__(
        self,
        text: str,
        *,
        delta: bool = True,
        msg_id: str = "m1",
        index: int = 0,
    ) -> None:
        self.text = text
        self.delta = delta
        self.msg_id = msg_id
        self.index = index

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "object": self.object,
            "type": "text",
            "delta": self.delta,
            "msg_id": self.msg_id,
            "index": self.index,
            "text": self.text,
        }

    def model_dump_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)


def _channel() -> BaseChannel:
    # The SSE helpers only touch static methods, so skip __init__.
    return object.__new__(BaseChannel)


def _text_of(raw: str) -> str:
    return json.loads(raw).get("text", "")


def _message(role: Role = Role.ASSISTANT, **kwargs: Any) -> Message:
    return Message(id="m1", role=role, object="message", **kwargs)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("<system-notification>hidden</system-notification>answer", "answer"),
        ("<system-notification>hidden</notification>answer", "answer"),
        ("<system-long-custom-name />answer", "answer"),
        (
            "<system-info>hidden</system-warning>still hidden</system-info>answer",
            "answer",
        ),
        (
            "```xml\nexample\n```\n<thinking>hidden</thinking>answer",
            "```xml\nexample\n```\nanswer",
        ),
        ("~~~xml\n<thinking>literal</thinking>\n~~~\nanswer", None),
        ("~~~xml\n~~~not a closer\n<thinking>literal</thinking>\n~~~", None),
        ("example ``<thinking>literal</thinking>`` answer", None),
        ('<parameter name="count">3</parameter>', None),
        ('<parameter name="count">hidden', ""),
    ],
)
def test_sse_filter_is_independent_of_chunk_boundaries(
    source: str,
    expected: str | None,
) -> None:
    channel = _channel()
    fragments: list[tuple[str, ...]] = [
        (source[:i], source[i:]) for i in range(len(source) + 1)
    ]
    fragments.append(tuple(source))
    for chunks in fragments:
        states: dict[str, Any] = {}
        channel._serialize_event_for_sse(_message(), states)
        output = [
            _text_of(
                channel._serialize_event_for_sse(_ContentEvent(t), states),
            )
            for t in chunks
        ]
        output.extend(
            _text_of(item)
            for item in channel._flush_headline_stream_states(states)
        )
        assert "".join(output) == (source if expected is None else expected), (
            chunks,
            output,
        )


@pytest.mark.asyncio
async def test_sse_hides_scaffolding_across_runtime_content_indexes() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    envelope = Envelope()
    texts = ("<thinking>hidden", "private middle", "</thinking>answer")
    expected = ("", "", "answer")

    for i, (text, visible) in enumerate(zip(texts, expected)):
        for kind in (EventType.TEXT_BLOCK_DELTA, EventType.TEXT_BLOCK_END):
            event = SimpleNamespace(type=kind, block_id=str(i), delta=text)
            async for item in envelope.translate_event(event):
                payload = json.loads(
                    channel._serialize_event_for_sse(item, states),
                )
                if payload["object"] == "content":
                    assert payload["text"] == visible

    message, response = [item async for item in envelope.finalize()]
    assert not channel._flush_headline_stream_states(states, msg_id=message.id)
    completed = json.loads(channel._serialize_event_for_sse(message, states))
    final = json.loads(channel._serialize_event_for_sse(response, states))
    assert tuple(c["text"] for c in completed["content"]) == expected
    assert tuple(c["text"] for c in final["output"][0]["content"]) == expected
    assert tuple(c.text for c in message.content) == texts


@pytest.mark.parametrize("role", [Role.USER, Role.TOOL])
def test_sse_leaves_non_assistant_text_unchanged(role: Role) -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    text = "<thinking>literal document content</thinking>"
    message = _message(role)
    channel._serialize_event_for_sse(message, states)
    event = TextContent(text=text, index=0, msg_id=message.id, delta=True)
    assert _text_of(channel._serialize_event_for_sse(event, states)) == text

    message.content.append(TextContent(text=text, index=0))
    payload = json.loads(channel._serialize_event_for_sse(message, states))
    assert payload["content"][0]["text"] == text


def test_sse_leaves_structured_tool_payloads_unchanged() -> None:
    channel = _channel()
    text = "<thinking>literal document content</thinking>"
    content = DataContent(data={"output": [{"type": "text", "text": text}]})
    message = _message(
        Role.TOOL,
        type=MessageType.FUNCTION_CALL_OUTPUT,
        content=[content],
    ).completed()
    reasoning = Message(
        type=MessageType.REASONING,
        role=Role.ASSISTANT,
        content=[TextContent(text=text)],
    ).completed()
    response = AgentResponse(output=[message, reasoning], object="response")
    payload = json.loads(channel._serialize_event_for_sse(response, {}))
    assert payload["output"][0]["content"][0]["data"] == content.data
    assert payload["output"][1]["content"][0]["text"] == text


def test_sse_deltas_hide_a_thinking_block_split_across_events() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    channel._serialize_event_for_sse(_message(), states)
    chunks = ("<thin", "king>secret plan", "</thin", "king>the answer")

    visible = "".join(
        _text_of(
            channel._serialize_event_for_sse(_ContentEvent(chunk), states),
        )
        for chunk in chunks
    )

    assert visible == "the answer"
    # 12th review: the scanner has to live for the whole message, so its
    # state stays until the message completes instead of being dropped once
    # a single delta happens to look clean.
    assert set(states) == {"scaffold:m1"}


def test_sse_whole_message_event_hides_scaffolding() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    channel._serialize_event_for_sse(_message(), states)

    raw = channel._serialize_event_for_sse(
        _ContentEvent(
            "<thinking>secret</thinking>visible answer",
            delta=False,
        ),
        states,
    )

    assert _text_of(raw) == "visible answer"


def test_sse_flush_releases_pending_scaffold_prefix() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    channel._serialize_event_for_sse(_message(), states)

    _text_of(
        channel._serialize_event_for_sse(_ContentEvent("compare <"), states),
    )
    flushed = [
        _text_of(item)
        for item in BaseChannel._flush_headline_stream_states(states)
    ]

    assert "".join(flushed) == "<"
    assert states == {}
