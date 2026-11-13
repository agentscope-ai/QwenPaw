# -*- coding: utf-8 -*-
"""Functional tests for tool-result snapshot gating."""
from __future__ import annotations

import json
from typing import Any

import pytest
from agentscope.event import (
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultDataDeltaEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import ToolResultState

import qwenpaw.runtime.envelope as envelope_module
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import RunStatus

CALL_ID = "call-gate"
TOOL_NAME = "execute_shell_command"
REPLY_ID = "reply-gate"


async def _drain(envelope: Envelope, event: Any) -> list[Any]:
    """Translate one event and collect its outputs."""
    return [item async for item in envelope.translate_event(event)]


async def _start_call(envelope: Envelope) -> None:
    """Open a tool call."""
    await _drain(
        envelope,
        ToolCallStartEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            tool_call_name=TOOL_NAME,
        ),
    )


async def _start_result(envelope: Envelope) -> None:
    """Open a tool result."""
    await _drain(
        envelope,
        ToolResultStartEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            tool_call_name=TOOL_NAME,
        ),
    )


async def _text_delta(envelope: Envelope, text: str) -> list[Any]:
    """Feed one tool-result text fragment."""
    return await _drain(
        envelope,
        ToolResultTextDeltaEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            delta=text,
        ),
    )


async def _end_result(envelope: Envelope) -> list[Any]:
    """Complete a tool result."""
    return await _drain(
        envelope,
        ToolResultEndEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            state=ToolResultState.SUCCESS,
        ),
    )


@pytest.fixture(autouse=True)
def _small_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use small thresholds so functional tests need tiny payloads."""
    monkeypatch.setattr(
        envelope_module,
        "TOOL_RESULT_SNAPSHOT_MIN_BYTES",
        4,
    )
    monkeypatch.setattr(
        envelope_module,
        "TOOL_RESULT_SNAPSHOT_GROWTH",
        2,
    )


async def test_text_gate_preserves_complete_terminal_output() -> None:
    """Suppressed fragments still appear in the terminal snapshot."""
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    emitted = [
        await _text_delta(envelope, fragment)
        for fragment in ("ab", "cd", "ef", "gh")
    ]
    terminal = await _end_result(envelope)

    assert [len(items) for items in emitted] == [1, 1, 0, 1]
    assert terminal[0].data["output"] == "abcdefgh"
    assert terminal[0].status == RunStatus.Completed


async def test_cancel_collects_suppressed_text() -> None:
    """Cancellation reads accumulated state, including hidden fragments."""
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    await _text_delta(envelope, "ab")
    await _text_delta(envelope, "cd")
    assert await _text_delta(envelope, "ef") == []

    assert envelope.collect_tool_output()[CALL_ID] == "abcdef"


async def test_data_fragments_are_complete_in_terminal_snapshot() -> None:
    """Suppressed base64 fragments remain in the final image block."""
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    for data in ("AA", "BB", "CC"):
        await _drain(
            envelope,
            ToolResultDataDeltaEvent(
                reply_id=REPLY_ID,
                tool_call_id=CALL_ID,
                block_id="image",
                media_type="image/png",
                data=data,
            ),
        )
    terminal = await _end_result(envelope)

    blocks = json.loads(terminal[0].data["output"])
    assert blocks == [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "data": "AABBCC",
                "media_type": "image/png",
            },
        },
    ]


async def test_tool_call_arguments_are_not_gated() -> None:
    """The result gate does not suppress tool-call argument deltas."""
    envelope = Envelope(session_id="gate")
    await _start_call(envelope)

    emitted = []
    for fragment in ('{"command":', '"pwd"}'):
        emitted.extend(
            await _drain(
                envelope,
                ToolCallDeltaEvent(
                    reply_id=REPLY_ID,
                    tool_call_id=CALL_ID,
                    delta=fragment,
                ),
            ),
        )
    terminal = await _drain(
        envelope,
        ToolCallEndEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
        ),
    )

    assert [item.data["arguments"] for item in emitted] == [
        '{"command":',
        '"pwd"}',
    ]
    assert terminal[0].data["arguments"] == '{"command":"pwd"}'


async def test_terminal_snapshots_keep_their_existing_shape() -> None:
    """The gate does not inject message ids into terminal content."""
    envelope = Envelope(session_id="gate")
    await _start_call(envelope)
    call_terminal = await _drain(
        envelope,
        ToolCallEndEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
        ),
    )

    await _start_result(envelope)
    await _text_delta(envelope, "done")
    result_terminal = await _end_result(envelope)

    assert call_terminal[0].msg_id is None
    assert result_terminal[0].msg_id is None
    assert result_terminal[-1].object == "message"
