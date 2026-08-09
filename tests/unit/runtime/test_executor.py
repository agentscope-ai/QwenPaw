# -*- coding: utf-8 -*-
"""Agent execution event-to-state behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.event import ReplyEndEvent
from agentscope.message import Msg

from qwenpaw.runtime.executor import AgentExecutor

pytestmark = [pytest.mark.unit, pytest.mark.p1]


class _RecordingEnvelope:
    def __init__(self) -> None:
        self.events = []

    async def heartbeat(self):
        for item in ():
            yield item

    async def translate_event(self, event):
        self.events.append(event)
        for item in ():
            yield item


class _ReplyingAgent:
    def __init__(self, context: list[Msg], event: ReplyEndEvent) -> None:
        self.state = SimpleNamespace(context=context)
        self._event = event

    async def reply_stream(self, inputs):
        del inputs
        yield self._event


async def test_reply_end_event_stamps_only_matching_context_message():
    historical = Msg(
        id="reply-old",
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "old reply"}],
    )
    current = Msg(
        id="reply-current",
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": "current reply"}],
    )
    event = ReplyEndEvent(
        session_id="session-1",
        reply_id="reply-current",
        created_at="2026-08-08T10:02:00+00:00",
    )
    envelope = _RecordingEnvelope()
    executor = AgentExecutor(
        _ReplyingAgent([historical, current], event),
        envelope,
    )

    assert [item async for item in executor.run([])] == []

    assert historical.finished_at is None
    assert current.finished_at == "2026-08-08T10:02:00+00:00"
    assert envelope.events == [event]
