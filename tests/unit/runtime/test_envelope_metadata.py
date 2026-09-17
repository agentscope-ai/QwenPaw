# -*- coding: utf-8 -*-
"""Tests for AgentScope event metadata in real-time envelopes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest
from agentscope.event import EventType

from qwenpaw.runtime.envelope import Envelope, _propagate_event_metadata
from qwenpaw.schemas import ContentType, MessageType, RunStatus, TextContent


class _SyntheticEnvelope(Envelope):
    """Envelope with one output for testing metadata propagation."""

    @_propagate_event_metadata
    async def translate_event(
        self,
        event: Any,
    ) -> AsyncGenerator[Any, None]:
        del event
        output = TextContent(
            type=ContentType.TEXT,
            text="synthetic",
            delta=True,
            index=0,
        )
        yield self._tag_seq(output)


def _event(event_type: EventType, **fields: Any) -> SimpleNamespace:
    metadata = fields.pop("metadata", {"event": event_type.value})
    return SimpleNamespace(
        type=event_type.value,
        metadata=metadata,
        **fields,
    )


async def _dump(
    stream: AsyncGenerator[Any, None],
) -> list[dict[str, Any]]:
    """Dump each yielded object immediately, as the SSE consumer does."""
    return [item.model_dump(mode="python") async for item in stream]


async def _translate(
    envelope: Envelope,
    event: SimpleNamespace,
) -> list[dict[str, Any]]:
    return await _dump(envelope.translate_event(event))


def _assert_no_metadata(value: Any) -> None:
    if isinstance(value, dict):
        assert not value.get("metadata")
        for nested in value.values():
            _assert_no_metadata(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_metadata(nested)


@pytest.mark.asyncio
async def test_event_metadata_decorator_applies_to_outputs_by_default():
    envelope = _SyntheticEnvelope()
    event = _event(
        EventType.TEXT_BLOCK_DELTA,
        metadata={"route": "node-a"},
    )

    [payload] = await _translate(envelope, event)

    assert payload["sequence_number"] == 1
    assert payload["metadata"] == {"route": "node-a"}


@pytest.mark.asyncio
async def test_metadata_is_added_to_existing_stream_outputs():
    cases = [
        (
            [
                _event(EventType.TEXT_BLOCK_START, block_id="text"),
                _event(
                    EventType.TEXT_BLOCK_DELTA,
                    block_id="text",
                    delta="hello",
                ),
                _event(EventType.TEXT_BLOCK_END, block_id="text"),
            ],
            [1, 1, 1],
        ),
        (
            [
                _event(EventType.THINKING_BLOCK_START, block_id="thinking"),
                _event(
                    EventType.THINKING_BLOCK_DELTA,
                    block_id="thinking",
                    delta="considering",
                ),
                _event(EventType.THINKING_BLOCK_END, block_id="thinking"),
            ],
            [1, 1, 2],
        ),
        (
            [
                _event(
                    EventType.TOOL_CALL_START,
                    tool_call_id="call",
                    tool_call_name="lookup",
                ),
                _event(
                    EventType.TOOL_CALL_DELTA,
                    tool_call_id="call",
                    delta='{"q":"hello"}',
                ),
                _event(EventType.TOOL_CALL_END, tool_call_id="call"),
            ],
            [2, 1, 2],
        ),
        (
            [
                _event(
                    EventType.TOOL_RESULT_START,
                    tool_call_id="result",
                    tool_call_name="lookup",
                ),
                _event(
                    EventType.TOOL_RESULT_TEXT_DELTA,
                    tool_call_id="result",
                    delta="done",
                ),
                _event(
                    EventType.TOOL_RESULT_DATA_DELTA,
                    tool_call_id="result",
                    block_id="image",
                    media_type="image/png",
                    data="YWJj",
                    url=None,
                ),
                _event(
                    EventType.TOOL_RESULT_END,
                    tool_call_id="result",
                    state="success",
                ),
            ],
            [2, 1, 1, 2],
        ),
        (
            [
                _event(
                    EventType.DATA_BLOCK_START,
                    block_id="data",
                    media_type="image/png",
                ),
                _event(
                    EventType.DATA_BLOCK_DELTA,
                    block_id="data",
                    data="YWJj",
                ),
                _event(EventType.DATA_BLOCK_END, block_id="data"),
            ],
            [1, 0, 1],
        ),
    ]

    for events, expected_counts in cases:
        envelope = Envelope()
        for event, expected_count in zip(events, expected_counts):
            payloads = await _translate(envelope, event)
            assert len(payloads) == expected_count
            assert all(
                payload["metadata"] == event.metadata for payload in payloads
            )


@pytest.mark.asyncio
async def test_tool_metadata_is_scoped_to_its_own_outputs():
    envelope = Envelope()
    text_metadata = {"route": "text"}
    for event in (
        _event(
            EventType.TEXT_BLOCK_START,
            metadata=text_metadata,
            block_id="text",
        ),
        _event(
            EventType.TEXT_BLOCK_DELTA,
            metadata=text_metadata,
            block_id="text",
            delta="before tool",
        ),
        _event(
            EventType.TEXT_BLOCK_END,
            metadata=text_metadata,
            block_id="text",
        ),
    ):
        await _translate(envelope, event)

    tool_metadata = {"route": "call-a"}
    payloads = await _translate(
        envelope,
        _event(
            EventType.TOOL_CALL_START,
            metadata=tool_metadata,
            tool_call_id="call-a",
            tool_call_name="lookup",
        ),
    )

    # The first payload finalizes the preceding text message and is not
    # produced by the tool call itself.
    assert len(payloads) == 3
    assert payloads[0]["type"] == MessageType.MESSAGE
    assert payloads[0]["metadata"] is None
    assert all(
        payload["metadata"] == tool_metadata for payload in payloads[1:]
    )

    await _translate(
        envelope,
        _event(
            EventType.TOOL_CALL_START,
            metadata={"route": "call-b"},
            tool_call_id="call-b",
            tool_call_name="lookup",
        ),
    )
    for call_id in ("call-b", "call-a"):
        metadata = {"route": call_id}
        [payload] = await _translate(
            envelope,
            _event(
                EventType.TOOL_CALL_DELTA,
                metadata=metadata,
                tool_call_id=call_id,
                delta=call_id,
            ),
        )
        assert payload["metadata"] == metadata
        assert payload["data"] == {"arguments": call_id}


@pytest.mark.asyncio
async def test_metadata_cannot_override_host_fields():
    reserved = {
        "object": "plugin-object",
        "status": "failed",
        "sequence_number": 999,
        "msg_id": "plugin-message",
        "id": "plugin-id",
        "type": "plugin-type",
    }
    message, content = await _translate(
        Envelope(),
        _event(
            EventType.TOOL_CALL_START,
            metadata=reserved,
            tool_call_id="call",
            tool_call_name="lookup",
        ),
    )

    assert message["metadata"] == reserved
    assert message["object"] == "message"
    assert message["status"] == RunStatus.InProgress
    assert message["sequence_number"] == 1
    assert message["id"] != "plugin-id"
    assert message["type"] == MessageType.PLUGIN_CALL

    assert content["metadata"] == reserved
    assert content["object"] == "content"
    assert content["sequence_number"] == 2
    assert content["msg_id"] == message["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("finalizer", ["normal", "cancel", "error"])
async def test_finalize_does_not_promote_event_metadata(finalizer):
    envelope = Envelope()
    metadata = {"temporary_route": "node"}
    await _translate(
        envelope,
        _event(
            EventType.TEXT_BLOCK_DELTA,
            metadata=metadata,
            block_id="text",
            delta="partial",
        ),
    )

    if finalizer == "normal":
        payloads = await _dump(envelope.finalize())
    elif finalizer == "cancel":
        payloads = await _dump(envelope.cancel_envelope())
    else:
        payloads = await _dump(
            envelope.error_envelope("failed", "test_error"),
        )

    _assert_no_metadata(payloads)


@pytest.mark.asyncio
async def test_empty_metadata_keeps_existing_content_shape():
    envelope = Envelope()
    [message, delta] = await _translate(
        envelope,
        _event(
            EventType.TEXT_BLOCK_DELTA,
            metadata={},
            block_id="text",
            delta="hello",
        ),
    )

    assert message["metadata"] is None
    assert "metadata" not in delta
