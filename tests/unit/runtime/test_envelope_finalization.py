# -*- coding: utf-8 -*-
"""Terminal materialization tests for the native runtime envelope."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest
from agentscope.event import EventType

from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import (
    Message,
    MessageType,
    RunStatus,
)


async def _collect(stream: AsyncGenerator[Any, None]) -> list[Any]:
    return [item async for item in stream]


def _event(event_type: EventType, **kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(type=event_type.value, metadata=None, **kwargs)


@pytest.mark.asyncio
async def test_cancel_materializes_open_reasoning_before_response() -> None:
    envelope = Envelope(session_id="session-1")
    await _collect(
        envelope.translate_event(
            _event(
                EventType.THINKING_BLOCK_DELTA,
                block_id="reasoning-1",
                delta="partial reasoning",
            ),
        ),
    )

    finalized = await _collect(envelope.cancel_envelope())

    reasoning = next(
        item
        for item in finalized
        if isinstance(item, Message) and item.type == MessageType.REASONING
    )
    assert reasoning.status == RunStatus.Cancelled
    assert reasoning.content[0].text == "partial reasoning"
    assert finalized.index(reasoning) < len(finalized) - 1
    assert finalized[-1].status == RunStatus.Cancelled


@pytest.mark.asyncio
async def test_error_materializes_open_tool_call_and_output() -> None:
    envelope = Envelope(session_id="session-1")
    events = [
        _event(
            EventType.TOOL_CALL_START,
            tool_call_id="tool-1",
            tool_call_name="shell",
        ),
        _event(
            EventType.TOOL_CALL_DELTA,
            tool_call_id="tool-1",
            delta='{"command":"pytest',
        ),
        _event(
            EventType.TOOL_RESULT_START,
            tool_call_id="tool-1",
            tool_call_name="shell",
        ),
        _event(
            EventType.TOOL_RESULT_TEXT_DELTA,
            tool_call_id="tool-1",
            delta="1 passed",
        ),
    ]
    for event in events:
        await _collect(envelope.translate_event(event))

    finalized = await _collect(
        envelope.error_envelope("provider failed", "provider_error"),
    )

    messages = [item for item in finalized if isinstance(item, Message)]
    assert [message.type for message in messages] == [
        MessageType.PLUGIN_CALL,
        MessageType.PLUGIN_CALL_OUTPUT,
    ]
    assert all(message.status == RunStatus.Failed for message in messages)
    assert messages[0].content[0].data["arguments"] == ('{"command":"pytest')
    assert messages[1].content[0].data["output"] == "1 passed"
    assert finalized[-1].status == RunStatus.Failed
