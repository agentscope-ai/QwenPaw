# -*- coding: utf-8 -*-
"""Tests for carrying a loop-gate stop reason to the finalized reply.

A loop gate ends a turn by returning a normal-looking assistant message,
so nothing in the streamed output tells a cron job that the turn was
stopped. The reason travels out of band (agent -> executor -> envelope)
and is stamped on the finalized message metadata, which is what this
module pins down.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest
from agentscope.event import EventType

from qwenpaw.constant import QWENPAW_STOP_REASON_KEY
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.runtime.executor import AgentExecutor


class _RecordingEnvelope:
    """Minimal envelope that records the stop reason it is handed."""

    def __init__(self) -> None:
        self.reasons: list[str] = []

    async def heartbeat(self) -> AsyncGenerator[Any, None]:
        return
        yield  # pragma: no cover

    async def translate_event(
        self,
        event: Any,
    ) -> AsyncGenerator[Any, None]:
        del event
        return
        yield  # pragma: no cover

    def set_stop_reason(self, reason: str | None) -> None:
        if reason:
            self.reasons.append(reason)


def _agent(stop_reason: str | None) -> SimpleNamespace:
    agent = SimpleNamespace(stop_reason=stop_reason)

    async def reply_stream(inputs: Any) -> AsyncGenerator[Any, None]:
        del inputs
        yield SimpleNamespace(type=EventType.TEXT_BLOCK_START.value)

    agent.reply_stream = reply_stream
    return agent


@pytest.mark.asyncio
async def test_executor_hands_the_stop_reason_to_the_envelope() -> None:
    envelope = _RecordingEnvelope()
    executor = AgentExecutor(_agent("Doom loop: agent stuck"), envelope)

    async for _ in executor.run([]):
        pass

    assert envelope.reasons == ["Doom loop: agent stuck"]


@pytest.mark.asyncio
async def test_executor_skips_a_turn_that_was_not_stopped() -> None:
    envelope = _RecordingEnvelope()
    executor = AgentExecutor(_agent(None), envelope)

    async for _ in executor.run([]):
        pass

    assert envelope.reasons == []


@pytest.mark.asyncio
async def test_executor_tolerates_an_envelope_without_the_hook() -> None:
    """Older callers pass a duck-typed envelope; it must not break."""

    class _PlainEnvelope:
        async def heartbeat(self) -> AsyncGenerator[Any, None]:
            return
            yield  # pragma: no cover

        async def translate_event(
            self,
            event: Any,
        ) -> AsyncGenerator[Any, None]:
            del event
            return
            yield  # pragma: no cover

    executor = AgentExecutor(_agent("gate"), _PlainEnvelope())

    async for _ in executor.run([]):
        pass


async def _finish_text(envelope: Envelope, text: str) -> list[Any]:
    """Drive one text block through ``envelope`` and finalize it."""

    events = [
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_START.value,
            block_id="text",
        ),
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_DELTA.value,
            block_id="text",
            delta=text,
        ),
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_END.value,
            block_id="text",
        ),
    ]
    for event in events:
        async for _ in envelope.translate_event(event):
            pass
    return [item async for item in envelope.finalize()]


@pytest.mark.asyncio
async def test_finalized_message_carries_the_stop_reason() -> None:
    envelope = Envelope()
    envelope.set_stop_reason("Doom loop: agent stuck")

    finalized = await _finish_text(envelope, "Still polling.")

    message = finalized[0]
    assert message.metadata == {
        QWENPAW_STOP_REASON_KEY: "Doom loop: agent stuck",
    }
    assert finalized[0].metadata[QWENPAW_STOP_REASON_KEY] == (
        "Doom loop: agent stuck"
    )


@pytest.mark.asyncio
async def test_finalized_message_has_no_reason_without_a_gate_stop() -> None:
    envelope = Envelope()

    finalized = await _finish_text(envelope, "Done.")

    assert not finalized[0].metadata
