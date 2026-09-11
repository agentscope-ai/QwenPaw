# -*- coding: utf-8 -*-
"""Tests for lightweight runtime heartbeat events."""

import pytest

from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import (
    ContentType,
    Message,
    Role,
    RunStatus,
    TextContent,
)


@pytest.mark.asyncio
async def test_heartbeat_does_not_repeat_accumulated_response() -> None:
    envelope = Envelope(session_id="session-with-large-output")
    large_output = "x" * (1024 * 1024)
    envelope._response.output.append(  # pylint: disable=protected-access
        Message(
            role=Role.TOOL,
            status=RunStatus.Completed,
            content=[
                TextContent(
                    type=ContentType.TEXT,
                    text=large_output,
                ),
            ],
        ),
    )

    events = [event async for event in envelope.heartbeat()]

    assert len(events) == 1
    heartbeat = events[0]
    assert heartbeat.object == "message"
    assert heartbeat.type == "heartbeat"
    assert large_output not in heartbeat.model_dump_json()
    assert len(heartbeat.model_dump_json()) < 256


@pytest.mark.asyncio
async def test_heartbeat_keeps_accumulated_response_unchanged() -> None:
    envelope = Envelope(session_id="session")
    message = Message(
        role=Role.ASSISTANT,
        status=RunStatus.Completed,
        content=[TextContent(type=ContentType.TEXT, text="finished")],
    )
    envelope._response.output.append(  # pylint: disable=protected-access
        message,
    )

    _ = [event async for event in envelope.heartbeat()]

    assert envelope._response.output == [  # pylint: disable=protected-access
        message,
    ]
