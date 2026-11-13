# -*- coding: utf-8 -*-
"""Frame-translation tests: engine SSE frames → AgentScope events."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List

import pytest

from agentscope.event import (
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ThinkingBlockDeltaEvent,
    ThinkingBlockEndEvent,
    ThinkingBlockStartEvent,
)


async def _frames(
    items: List[Dict[str, Any]],
) -> AsyncIterator[Dict[str, Any]]:
    for item in items:
        yield item


def _msg_start(msg_id: str, mtype: str, seq: int) -> Dict[str, Any]:
    return {
        "object": "message",
        "id": msg_id,
        "type": mtype,
        "status": "in_progress",
        "sequence_number": seq,
    }


def _delta(msg_id: str, text: str, seq: int) -> Dict[str, Any]:
    return {
        "object": "content",
        "type": "text",
        "msg_id": msg_id,
        "delta": True,
        "text": text,
        "sequence_number": seq,
    }


def _full(msg_id: str, text: str, seq: int) -> Dict[str, Any]:
    return {
        "object": "content",
        "type": "text",
        "msg_id": msg_id,
        "delta": False,
        "text": text,
        "sequence_number": seq,
    }


def _response(status: str, seq: int, **extra: Any) -> Dict[str, Any]:
    return {
        "object": "response",
        "id": "resp_1",
        "status": status,
        "sequence_number": seq,
        **extra,
    }


async def _run(bridge_events, frames: List[Dict[str, Any]]):
    result = bridge_events.TurnResult()
    events = []
    async for event in bridge_events.translate_frames(
        _frames(frames),
        result,
        reply_id="r1",
    ):
        events.append(event)
    return events, result


@pytest.mark.asyncio
async def test_plain_answer_streams_text_blocks(bridge_events) -> None:
    events, result = await _run(
        bridge_events,
        [
            _response("in_progress", 1),
            _msg_start("m1", "message", 2),
            _delta("m1", "Hello ", 3),
            _delta("m1", "world", 4),
            _full("m1", "Hello world", 5),
            _response("completed", 6),
        ],
    )

    types = [type(e) for e in events]
    assert types == [
        TextBlockStartEvent,
        TextBlockDeltaEvent,
        TextBlockDeltaEvent,
        TextBlockEndEvent,
    ]
    assert result.answer == "Hello world"
    assert result.status == "completed"
    assert result.last_seq == 6


@pytest.mark.asyncio
async def test_reasoning_then_answer(bridge_events) -> None:
    events, result = await _run(
        bridge_events,
        [
            _msg_start("r1", "reasoning", 1),
            _delta("r1", "thinking...", 2),
            _msg_start("m1", "message", 3),
            _delta("m1", "answer", 4),
            _response("completed", 5),
        ],
    )

    types = [type(e) for e in events]
    assert types == [
        ThinkingBlockStartEvent,
        ThinkingBlockDeltaEvent,
        TextBlockStartEvent,
        TextBlockDeltaEvent,
        ThinkingBlockEndEvent,
        TextBlockEndEvent,
    ]
    assert result.answer == "answer"


@pytest.mark.asyncio
async def test_plugin_call_deltas_are_dropped(bridge_events) -> None:
    events, result = await _run(
        bridge_events,
        [
            _msg_start("m1", "message", 1),
            # plugin_call msg never enters the whitelist
            _delta("p1", '{"call": 1}', 2),
            _delta("m1", "clean", 3),
            _response("completed", 4),
        ],
    )

    assert result.answer == "clean"
    deltas = [e for e in events if isinstance(e, TextBlockDeltaEvent)]
    assert len(deltas) == 1


@pytest.mark.asyncio
async def test_multi_round_uses_separate_blocks(bridge_events) -> None:
    events, result = await _run(
        bridge_events,
        [
            _msg_start("m1", "message", 1),
            _delta("m1", "first", 2),
            _msg_start("m2", "message", 3),
            _delta("m2", "second", 4),
            _response("completed", 5),
        ],
    )

    starts = [e for e in events if isinstance(e, TextBlockStartEvent)]
    assert [s.block_id for s in starts] == ["m1", "m2"]
    assert result.answer == "firstsecond"


@pytest.mark.asyncio
async def test_non_streamed_full_content_emits_one_block(
    bridge_events,
) -> None:
    events, result = await _run(
        bridge_events,
        [
            _msg_start("m1", "message", 1),
            _full("m1", "replayed answer", 2),
            _response("completed", 3),
        ],
    )

    types = [type(e) for e in events]
    assert types == [
        TextBlockStartEvent,
        TextBlockDeltaEvent,
        TextBlockEndEvent,
    ]
    assert result.answer == "replayed answer"


@pytest.mark.asyncio
async def test_clarification_pauses_turn(bridge_events) -> None:
    plugin_call = {
        "object": "message",
        "id": "p1",
        "type": "plugin_call",
        "status": "completed",
        "sequence_number": 7,
        "content": [
            {
                "type": "data",
                "data": {
                    "call_id": "call_123",
                    "name": "ask_user_question",
                    "arguments": (
                        '{"title": "选择范围", "questions": [{'
                        '"question": "分析哪个季度?", '
                        '"multiSelect": false, '
                        '"options": [{"label": "Q1"}, {"label": "Q2"}]}]}'
                    ),
                },
            },
        ],
    }
    events, result = await _run(
        bridge_events,
        [
            _msg_start("m1", "message", 1),
            _delta("m1", "需要确认。", 2),
            plugin_call,
            # Frames after clarification must not be consumed
            _response("completed", 99),
        ],
    )

    assert result.status == "clarification"
    assert result.clarification is not None
    assert result.clarification.clarification_id == "call_123"
    assert result.clarification.questions[0]["options"][0]["label"] == "Q1"
    assert result.last_seq == 7
    assert isinstance(events[2], TextBlockEndEvent)
    assert events[2].block_id == "m1"
    assert isinstance(events[3], TextBlockStartEvent)
    assert events[3].block_id == "clarify-call_123"
    question_text = "".join(
        e.delta for e in events if isinstance(e, TextBlockDeltaEvent)
    )
    assert "分析哪个季度?" in question_text
    assert "1) Q1" in question_text


@pytest.mark.asyncio
async def test_error_only_stream_is_failed(bridge_events) -> None:
    _, result = await _run(
        bridge_events,
        [
            {
                "object": "error",
                "message": "runtime failed",
                "sequence_number": 1,
            },
        ],
    )

    assert result.status == "failed"
    assert result.failure_message == "runtime failed"


@pytest.mark.asyncio
async def test_terminal_response_refines_error_status(bridge_events) -> None:
    _, result = await _run(
        bridge_events,
        [
            {
                "object": "error",
                "message": "recoverable stream error",
                "sequence_number": 1,
            },
            _response("completed", 2),
        ],
    )

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_stream_eof_closes_open_text_and_thinking_blocks(
    bridge_events,
) -> None:
    events, result = await _run(
        bridge_events,
        [
            _msg_start("r1", "reasoning", 1),
            _delta("r1", "thinking", 2),
            _msg_start("m1", "message", 3),
            _delta("m1", "answer", 4),
        ],
    )

    assert [type(event) for event in events] == [
        ThinkingBlockStartEvent,
        ThinkingBlockDeltaEvent,
        TextBlockStartEvent,
        TextBlockDeltaEvent,
        ThinkingBlockEndEvent,
        TextBlockEndEvent,
    ]
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_failed_response_carries_message(bridge_events) -> None:
    _, result = await _run(
        bridge_events,
        [
            _response(
                "failed",
                3,
                error={"message": "model quota exceeded"},
            ),
        ],
    )

    assert result.status == "failed"
    assert result.failure_message == "model quota exceeded"


@pytest.mark.asyncio
async def test_artifacts_and_followups_collected(bridge_events) -> None:
    _, result = await _run(
        bridge_events,
        [
            {
                "object": "artifact.registered",
                "sequence_number": 1,
                "artifact": {"name": "trend.png", "path": "trend.png"},
            },
            {
                "object": "artifact.registered",
                "sequence_number": 2,
                "artifact": {"name": "trend.png", "path": "trend.png"},
            },
            {
                "object": "artifact.registered",
                "sequence_number": 3,
                "artifact": {"name": "data.csv", "path": "data.csv"},
            },
            {
                "object": "followup.generated",
                "sequence_number": 4,
                "followup": {"questions": ["为什么3月上涨?", "对比去年?"]},
            },
            _response("completed", 5),
        ],
    )

    assert [a["name"] for a in result.artifacts] == ["trend.png", "data.csv"]
    assert result.followups == ["为什么3月上涨?", "对比去年?"]


@pytest.mark.asyncio
async def test_emit_artifacts_images_and_notice(bridge_events) -> None:
    fetched: list = []

    async def fetch(path: str) -> bytes:
        fetched.append(path)
        return b"PNGDATA"

    events = []
    async for event in bridge_events.emit_artifacts(
        [
            {"name": "trend.png", "path": "charts/trend.png"},
            {"name": "data.csv", "path": "data.csv"},
        ],
        reply_id="r1",
        fetch=fetch,
    ):
        events.append(event)

    assert fetched == ["charts/trend.png"]
    types = [type(e) for e in events]
    assert types == [
        DataBlockStartEvent,
        DataBlockDeltaEvent,
        DataBlockEndEvent,
        TextBlockStartEvent,
        TextBlockDeltaEvent,
        TextBlockEndEvent,
    ]
    assert events[0].media_type == "image/png"
    assert events[1].data  # base64 payload present
    notice = events[4].delta
    assert "data.csv" in notice


@pytest.mark.asyncio
async def test_emit_artifacts_download_failure_degrades_to_notice(
    bridge_events,
) -> None:
    async def fetch(_path: str) -> bytes:
        raise RuntimeError("boom")

    events = []
    async for event in bridge_events.emit_artifacts(
        [{"name": "trend.png", "path": "trend.png"}],
        reply_id="r1",
        fetch=fetch,
    ):
        events.append(event)

    assert all(not isinstance(e, DataBlockStartEvent) for e in events)
    notice = "".join(
        e.delta for e in events if isinstance(e, TextBlockDeltaEvent)
    )
    assert "trend.png" in notice
