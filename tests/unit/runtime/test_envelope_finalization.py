# -*- coding: utf-8 -*-
"""Terminal materialization tests for the native runtime envelope."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest
from agentscope.event import EventType

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import TranscriptRecorder
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import (
    AgentRequest,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
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


@pytest.mark.asyncio
async def test_cancelled_reasoning_reaches_transcript(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    request = AgentRequest(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        input=[
            Message(
                id="user-message",
                role=Role.USER,
                content=[TextContent(text="question")],
            ),
        ],
    )
    recorder = TranscriptRecorder(
        store=store,
        request=request,
    )
    envelope = Envelope(session_id="session-1")
    await recorder.start()
    for item in await _collect(
        envelope.translate_event(
            _event(
                EventType.THINKING_BLOCK_DELTA,
                block_id="reasoning-1",
                delta="partial reasoning",
            ),
        ),
    ):
        await recorder.observe(item)
    for item in await _collect(envelope.cancel_envelope()):
        await recorder.observe(item)

    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.id for message in page.messages][0] == "user-message"
    assert page.messages[-1].type == MessageType.REASONING
    assert page.messages[-1].content[0].text == "partial reasoning"
    turn = store._conn.execute(  # pylint: disable=protected-access
        "SELECT status FROM transcript_turns",
    ).fetchone()
    assert turn["status"] == "cancelled"
    store.close()
