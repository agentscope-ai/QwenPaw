# -*- coding: utf-8 -*-
"""SSE content events must hide scaffolding, not only headlines."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agentscope.event import EventType

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.channel_protocol.models import RAW_COMPLETED_TEXT_CAPABILITY
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import (
    AgentRequest,
    AgentResponse,
    DataContent,
    Message,
    MessageType,
    Role,
    RunStatus,
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
        ("example `line one\n<thinking>literal</thinking>` answer", None),
        ('<parameter name="count">3</parameter>', None),
        ('<parameter name="count">hidden', ""),
        ('<thinking>hidden</thinking><parameter name="count">hidden', ""),
        (
            "<thinking><analysis>inner</analysis>private</thinking>answer",
            "answer",
        ),
        (
            "<thinking>example `</thinking>` private</thinking>answer",
            "answer",
        ),
        (
            "<thinking>\n```xml\n</thinking>\n```\nprivate</thinking>answer",
            "answer",
        ),
        (
            "<system-info><system-info>inner</system-info>"
            "private</system-info>answer",
            "answer",
        ),
        ("The <think> opener.\n\n```xml\n</think>\n```\nMore prose", None),
        ("The <think> opener.\n\n`</think>`\nMore prose", None),
        (
            "A stray `\n\n<system-info>private</system-info>answer",
            "A stray `\n\nanswer",
        ),
        (
            "<thinking>A stray ` before the close</thinking>answer",
            "answer",
        ),
        (
            r"Escaped \` <system-info>private</system-info>answer `",
            r"Escaped \` answer `",
        ),
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


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        (["private", "</think>answer"], ["", "answer"]),
        (["answer\n\nprivate", "</think>"], ["answer", ""]),
        (["first", "second"], ["first", "second"]),
    ],
)
def test_sse_defers_assistant_text_until_bare_close_is_resolved(
    blocks: list[str],
    expected: list[str],
) -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    message = _message()
    channel._serialize_event_for_sse(message, states)
    for index, text in enumerate(blocks):
        for delta in (True, False):
            event = _ContentEvent(text, index=index, delta=delta)
            assert (
                _text_of(channel._serialize_event_for_sse(event, states)) == ""
            )
        message.content.append(TextContent(text=text, index=index))

    flushed = channel._flush_headline_stream_states(states, msg_id=message.id)
    released = {
        item["index"]: item["text"] for item in map(json.loads, flushed)
    }
    assert [released.get(i, "") for i in range(len(blocks))] == expected
    completed = json.loads(
        channel._serialize_event_for_sse(message.completed()),
    )
    assert [c["text"] for c in completed["content"]] == expected


@pytest.mark.asyncio
async def test_sse_hides_scaffolding_across_runtime_content_indexes() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    envelope = Envelope()
    texts = ("<thinking>hidden", "private middle", "</thinking>answer")
    expected = ("", "", "answer")

    for i, text in enumerate(texts):
        for kind in (EventType.TEXT_BLOCK_DELTA, EventType.TEXT_BLOCK_END):
            event = SimpleNamespace(type=kind, block_id=str(i), delta=text)
            async for item in envelope.translate_event(event):
                payload = json.loads(
                    channel._serialize_event_for_sse(item, states),
                )
                if payload["object"] == "content":
                    assert payload["text"] == ""

    message, response = [item async for item in envelope.finalize()]
    [released] = channel._flush_headline_stream_states(
        states,
        msg_id=message.id,
    )
    assert json.loads(released)["index"] == 2
    assert _text_of(released) == "answer"
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

    assert visible == ""
    assert set(states) == {"scaffold:m1"}
    [released] = channel._flush_headline_stream_states(states)
    assert _text_of(released) == "the answer"


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

    assert _text_of(raw) == ""
    [released] = channel._flush_headline_stream_states(states)
    assert _text_of(released) == "visible answer"


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

    assert "".join(flushed) == "compare <"
    assert states == {}


def test_incomplete_sse_stream_drops_unclassified_assistant_text() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    channel._serialize_event_for_sse(_message(), states)
    channel._serialize_event_for_sse(_ContentEvent("unclassified"), states)

    assert not channel._flush_headline_stream_states(
        states,
        release_assistant=False,
    )
    assert states == {}


def test_sse_serialization_fallback_does_not_publish_unfiltered_text() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    channel._serialize_event_for_sse(_message(), states)
    raw = channel._serialize_event_for_sse(
        TextContent(
            text="private \ud800</think>answer",
            msg_id="m1",
            delta=True,
        ),
        states,
    )
    assert _text_of(raw) == ""
    [released] = channel._flush_headline_stream_states(states)
    assert _text_of(released) == "answer"


def test_sse_does_not_publish_an_unclassified_message_snapshot() -> None:
    channel = _channel()
    message = _message(content=[TextContent(text="private prefix")])
    payload = json.loads(channel._serialize_event_for_sse(message, {}))

    assert payload["content"][0]["text"] == ""
    assert message.content[0].text == "private prefix"


@pytest.mark.asyncio
async def test_cancelled_snapshot_includes_bare_close_in_unfinished_block() -> None:
    channel = _channel()
    envelope = Envelope()
    events = [
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_DELTA,
            block_id="first",
            delta="private",
        ),
        SimpleNamespace(type=EventType.TEXT_BLOCK_END, block_id="first"),
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_DELTA,
            block_id="last",
            delta="</think>answer",
        ),
    ]
    for event in events:
        async for _ in envelope.translate_event(event):
            pass

    message, response = [item async for item in envelope.cancel_envelope()]
    for snapshot in (message, response):
        payload = channel._serialize_event_for_sse(snapshot)
        assert "private" not in payload
        assert "answer" in payload


@pytest.mark.parametrize(
    "status",
    [RunStatus.Completed, RunStatus.Cancelled, RunStatus.Failed],
)
async def test_terminal_snapshots_order_interleaved_blocks(
    status: RunStatus,
) -> None:
    channel = _channel()
    envelope = Envelope()
    states: dict[str, Any] = {}
    for kind, block, text in (
        (EventType.TEXT_BLOCK_DELTA, "first", "private scratchpad"),
        (EventType.TEXT_BLOCK_DELTA, "last", "</think>answer"),
        (EventType.TEXT_BLOCK_END, "last", ""),
    ):
        event = SimpleNamespace(type=kind, block_id=block, delta=text)
        async for item in envelope.translate_event(event):
            payload = channel._serialize_event_for_sse(item, states)
            assert "private scratchpad" not in payload

    terminal = {
        RunStatus.Completed: envelope.finalize,
        RunStatus.Cancelled: envelope.cancel_envelope,
        RunStatus.Failed: lambda: envelope.error_envelope("test failure"),
    }
    message, response = [item async for item in terminal[status]()]
    assert [block.text for block in message.content] == [
        "private scratchpad",
        "</think>answer",
    ]
    [released] = channel._flush_headline_stream_states(
        states,
        msg_id=message.id,
    )
    assert _text_of(released) == "answer"
    for snapshot in (message, response):
        payload = channel._serialize_event_for_sse(snapshot)
        assert "private scratchpad" not in payload
        assert "answer" in payload


@pytest.mark.parametrize("mode", ["content", "text_sources"])
@pytest.mark.parametrize("reply", ["answer", ""])
async def test_raw_voice_delivery_filters_before_projection(
    mode: str,
    reply: str,
) -> None:
    event = _message(
        status=RunStatus.Completed,
        content=[
            TextContent(text="<thinking>private"),
            TextContent(text=f"scratchpad</thinking>{reply}"),
        ],
    )
    before = event.model_dump()
    proxy = object.__new__(IsolatedChannelProxy)
    proxy.descriptor = SimpleNamespace(
        capabilities={RAW_COMPLETED_TEXT_CAPABILITY},
    )
    proxy._response_policy = AsyncMock(
        return_value=ResponsePolicy(raw_completed_text=mode),
    )
    proxy._send_operation = AsyncMock()

    await proxy._send_completed_event(None, "voice", event, {})

    assert event.model_dump() == before
    if not reply:
        proxy._send_operation.assert_not_awaited()
        return
    [call] = proxy._send_operation.await_args_list
    assert [part["text"] for part in call.kwargs["content_parts"]] == [reply]
    assert "private" not in json.dumps(call.kwargs)
    if mode == "text_sources":
        sources = call.kwargs["raw_completed_text_sources"]
        assert sources["top_texts"] == [reply]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [RunStatus.Completed, RunStatus.Cancelled, RunStatus.Failed],
)
async def test_console_terminal_snapshot_is_authoritative(
    status: RunStatus,
) -> None:
    async def process(_request):
        message = _message()
        yield message
        yield TextContent(
            text="private scratchpad",
            msg_id=message.id,
            index=0,
            delta=True,
        )
        message.content = [
            TextContent(text="private scratchpad</think>answer", index=0),
        ]
        message.status = status
        yield message
        yield AgentResponse(object="response", status=status, output=[message])

    channel = ConsoleChannel(process=process, enabled=True, bot_prefix="")
    channel._commit_turn_usage = AsyncMock(return_value=[])
    lines = [
        line async for line in channel.stream_one(AgentRequest(user_id="u"))
    ]
    assert "private scratchpad" not in "".join(lines)
    events = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert [e["text"] for e in events if e["object"] == "content"] == [
        "",
        "answer",
    ]


async def test_console_drops_text_without_a_message_snapshot() -> None:
    async def process(_request):
        message = _message()
        yield message
        yield TextContent(text="unclassified", msg_id=message.id, delta=True)
        yield AgentResponse(object="response", status=RunStatus.Failed)

    channel = ConsoleChannel(process=process, enabled=True, bot_prefix="")
    channel._commit_turn_usage = AsyncMock(return_value=[])
    lines = [
        line async for line in channel.stream_one(AgentRequest(user_id="u"))
    ]
    assert "unclassified" not in "".join(lines)


@pytest.mark.parametrize(
    "status",
    [RunStatus.Completed, RunStatus.Cancelled, RunStatus.Failed, None],
)
async def test_console_releases_answer_only_at_message_end(
    status: RunStatus | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def process(_request):
        message = _message()
        yield message
        for text in ("private scratchpad", "</think>public answer"):
            yield TextContent(
                text=text,
                msg_id=message.id,
                index=0,
                delta=True,
            )
        if status is not None:
            message.content.append(
                TextContent(text="private scratchpad</think>public answer"),
            )
            message.status = status
            yield message
            yield AgentResponse(
                object="response",
                status=status,
                output=[message],
            )

    channel = ConsoleChannel(process=process, enabled=True, bot_prefix="")
    monkeypatch.setattr(
        channel,
        "_commit_turn_usage",
        AsyncMock(return_value=[]),
    )
    lines = [
        line async for line in channel.stream_one(AgentRequest(user_id="u"))
    ]
    events = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert "private scratchpad" not in "".join(lines)
    assert [
        item["text"] for item in events if item.get("object") == "content"
    ] == (["", ""] if status is None else ["", "", "public answer"])
