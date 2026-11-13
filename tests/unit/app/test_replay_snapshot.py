# -*- coding: utf-8 -*-
"""Tests for materialized reconnect replay snapshots."""

from __future__ import annotations

import json

from qwenpaw.app.replay_store import ReplayStore
from qwenpaw.app.replay_snapshot import materialize_replay


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def _payload(frame: str) -> dict:
    return json.loads(frame[len("data: ") :])


def test_materializes_reasoning_and_tool_messages() -> None:
    events = [
        _sse(
            {
                "id": "response-1",
                "object": "response",
                "status": "in_progress",
                "output": [],
            },
        ),
        _sse(
            {
                "id": "reason-1",
                "object": "message",
                "type": "reasoning",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        ),
        _sse(
            {
                "type": "text",
                "object": "content",
                "msg_id": "reason-1",
                "delta": True,
                "text": "inspect ",
            },
        ),
        _sse(
            {
                "type": "text",
                "object": "content",
                "msg_id": "reason-1",
                "delta": True,
                "text": "files",
            },
        ),
        _sse(
            {
                "id": "tool-1",
                "object": "message",
                "type": "tool_call",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        ),
        _sse(
            {
                "type": "data",
                "object": "content",
                "msg_id": "tool-1",
                "delta": True,
                "data": {
                    "call_id": "call-1",
                    "name": "read_file",
                    "arguments": '{"path":',
                },
            },
        ),
        _sse(
            {
                "type": "data",
                "object": "content",
                "msg_id": "tool-1",
                "delta": True,
                "data": {"arguments": '"README.md"}'},
            },
        ),
        _sse(
            {
                "id": "tool-result-1",
                "object": "message",
                "type": "tool_call_output",
                "role": "tool",
                "status": "completed",
                "content": [
                    {
                        "type": "data",
                        "data": {
                            "call_id": "call-1",
                            "output": "done",
                        },
                    },
                ],
            },
        ),
        _sse({"type": "turn_usage", "tokens": 42}),
    ]

    materialized = materialize_replay(events)

    assert len(materialized) == 2
    assert _payload(materialized[0]) == {
        "type": "turn_usage",
        "tokens": 42,
    }
    snapshot = _payload(materialized[1])
    assert [item["id"] for item in snapshot["output"]] == [
        "reason-1",
        "tool-1",
        "tool-result-1",
    ]
    assert snapshot["output"][0]["content"][0]["text"] == "inspect files"
    assert snapshot["output"][1]["content"][0]["data"]["arguments"] == (
        '{"path":"README.md"}'
    )


def test_materializes_real_folded_terminal_replay_in_safe_order() -> None:
    response = {
        "id": "response-1",
        "object": "response",
        "status": "in_progress",
        "output": [],
    }
    message = {
        "id": "assistant-1",
        "object": "message",
        "type": "message",
        "role": "assistant",
        "status": "in_progress",
        "content": [],
    }
    tool_message = {
        "id": "tool-1",
        "object": "message",
        "type": "tool_call_output",
        "role": "tool",
        "status": "completed",
        "content": [
            {
                "type": "data",
                "data": {"call_id": "call-1", "output": "kept"},
            },
        ],
    }
    content = {
        "type": "text",
        "object": "content",
        "msg_id": "assistant-1",
        "delta": True,
        "text": "partial",
    }
    usage = {"type": "turn_usage", "tokens": 42}
    terminal = {
        **response,
        "status": "completed",
        "output": [
            {
                **message,
                "status": "completed",
                "content": [{"type": "text", "text": "complete"}],
            },
        ],
    }
    store = ReplayStore()
    events: list[dict] = [
        response,
        message,
        content,
        tool_message,
        usage,
        terminal,
    ]
    for event in events:
        store.append(_sse(event))

    materialized = materialize_replay(list(store.replay()))

    assert len(materialized) == 2
    assert _payload(materialized[0]) == usage
    snapshot = _payload(materialized[1])
    assert snapshot["status"] == "completed"
    assert snapshot["output"][0]["content"][0]["text"] == "complete"
    assert snapshot["output"][1] == tool_message


def test_preserves_terminal_status_and_canonical_output() -> None:
    initial = _sse(
        {
            "id": "response-1",
            "object": "response",
            "status": "in_progress",
            "output": [],
        },
    )
    terminal = _sse(
        {
            "id": "response-1",
            "object": "response",
            "status": "cancelled",
            "error": {"message": "stopped"},
            "output": [
                {
                    "id": "assistant-1",
                    "object": "message",
                    "type": "message",
                    "role": "assistant",
                    "status": "cancelled",
                    "content": [{"type": "text", "text": "partial"}],
                },
            ],
        },
    )

    snapshot = _payload(materialize_replay([initial, terminal])[0])

    assert snapshot["status"] == "cancelled"
    assert snapshot["error"] == {"message": "stopped"}
    assert snapshot["output"][0]["content"][0]["text"] == "partial"


def test_falls_back_to_original_replay_when_content_has_no_message() -> None:
    events = [
        _sse(
            {
                "id": "response-1",
                "object": "response",
                "status": "in_progress",
                "output": [],
            },
        ),
        _sse(
            {
                "type": "text",
                "object": "content",
                "msg_id": "missing",
                "delta": True,
                "text": "keep me",
            },
        ),
    ]

    assert materialize_replay(events) == events
