# -*- coding: utf-8 -*-
"""Envelope reasoning/text ordering across ReAct iterations.

Regression guard for the goal-mode bug where every iteration's answer text
merged into the first message (fixed early in ``output``) while each later
reasoning block was appended to the end, making the "Thinking" bubbles pile
up *below* the answer instead of interleaving with it.

The fix rotates (finalizes) the pending text message when a new reasoning
block starts, so each iteration becomes its own message ordered *before*
that iteration's reasoning.
"""

from __future__ import annotations

import asyncio
from typing import Any, List

from agentscope.event import EventType

from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import MessageType


class _FakeEvent:
    """Minimal stand-in for an agentscope streaming event."""

    def __init__(self, event_type: Any, **kwargs: Any) -> None:
        self.type = event_type
        for key, value in kwargs.items():
            setattr(self, key, value)


async def _drive(events: List[_FakeEvent]) -> Envelope:
    env = Envelope(session_id="console:default")
    for ev in events:
        async for _ in env.translate_event(ev):
            pass
    async for _ in env.finalize():
        pass
    return env


def _text_of(message: Any) -> str:
    parts = []
    for c in message.content:
        ctype = getattr(c, "type", None)
        ctype = getattr(ctype, "value", ctype)
        if ctype == "text":
            parts.append(getattr(c, "text", "") or "")
    return "".join(parts)


def _emitted_message_order(env: Envelope) -> List[Any]:
    """Distinct message envelopes in ``output``, in append order."""
    return list(env.response.output)


def test_reasoning_interleaves_between_iteration_texts() -> None:
    """text1 -> reasoning -> text2 must render as M1, R, M2 (interleaved),
    with the two answers kept in *separate* messages (not merged)."""

    events = [
        # iteration 1 answer
        _FakeEvent(EventType.TEXT_BLOCK_START, block_id="b1"),
        _FakeEvent(
            EventType.TEXT_BLOCK_DELTA, block_id="b1", delta="answer-1"
        ),
        _FakeEvent(EventType.TEXT_BLOCK_END, block_id="b1"),
        # iteration 2 begins with a reasoning block
        _FakeEvent(EventType.THINKING_BLOCK_START, block_id="t1"),
        _FakeEvent(
            EventType.THINKING_BLOCK_DELTA, block_id="t1", delta="think"
        ),
        _FakeEvent(EventType.THINKING_BLOCK_END, block_id="t1"),
        # iteration 2 answer
        _FakeEvent(EventType.TEXT_BLOCK_START, block_id="b2"),
        _FakeEvent(
            EventType.TEXT_BLOCK_DELTA, block_id="b2", delta="answer-2"
        ),
        _FakeEvent(EventType.TEXT_BLOCK_END, block_id="b2"),
    ]

    env = asyncio.run(_drive(events))
    output = _emitted_message_order(env)

    types = [m.type for m in output]
    assert types == [
        MessageType.MESSAGE,
        MessageType.REASONING,
        MessageType.MESSAGE,
    ], f"expected M, R, M interleaving, got {types}"

    text_msgs = [m for m in output if m.type == MessageType.MESSAGE]
    # Two *separate* answers, not merged into one block.
    assert len(text_msgs) == 2
    assert text_msgs[0].id != text_msgs[1].id
    assert _text_of(text_msgs[0]) == "answer-1"
    assert _text_of(text_msgs[1]) == "answer-2"


def test_reasoning_before_any_text_does_not_emit_empty_message() -> None:
    """A reasoning block that precedes any text (normal first iteration)
    must not spuriously finalize an empty text message."""

    events = [
        _FakeEvent(EventType.THINKING_BLOCK_START, block_id="t1"),
        _FakeEvent(
            EventType.THINKING_BLOCK_DELTA, block_id="t1", delta="think"
        ),
        _FakeEvent(EventType.THINKING_BLOCK_END, block_id="t1"),
        _FakeEvent(EventType.TEXT_BLOCK_START, block_id="b1"),
        _FakeEvent(
            EventType.TEXT_BLOCK_DELTA, block_id="b1", delta="answer"
        ),
        _FakeEvent(EventType.TEXT_BLOCK_END, block_id="b1"),
    ]

    env = asyncio.run(_drive(events))
    output = _emitted_message_order(env)

    types = [m.type for m in output]
    assert types == [MessageType.REASONING, MessageType.MESSAGE], types
    text_msgs = [m for m in output if m.type == MessageType.MESSAGE]
    assert len(text_msgs) == 1
    assert _text_of(text_msgs[0]) == "answer"


def test_delta_only_reasoning_also_rotates_pending_text() -> None:
    """A reasoning block delivered via DELTA without START still rotates the
    pending text message (fallback path parity)."""

    events = [
        _FakeEvent(EventType.TEXT_BLOCK_START, block_id="b1"),
        _FakeEvent(
            EventType.TEXT_BLOCK_DELTA, block_id="b1", delta="answer-1"
        ),
        _FakeEvent(EventType.TEXT_BLOCK_END, block_id="b1"),
        # reasoning arrives as DELTA only (no START event)
        _FakeEvent(
            EventType.THINKING_BLOCK_DELTA, block_id="t1", delta="think"
        ),
        _FakeEvent(EventType.THINKING_BLOCK_END, block_id="t1"),
        _FakeEvent(EventType.TEXT_BLOCK_START, block_id="b2"),
        _FakeEvent(
            EventType.TEXT_BLOCK_DELTA, block_id="b2", delta="answer-2"
        ),
        _FakeEvent(EventType.TEXT_BLOCK_END, block_id="b2"),
    ]

    env = asyncio.run(_drive(events))
    types = [m.type for m in _emitted_message_order(env)]
    assert types == [
        MessageType.MESSAGE,
        MessageType.REASONING,
        MessageType.MESSAGE,
    ], types
