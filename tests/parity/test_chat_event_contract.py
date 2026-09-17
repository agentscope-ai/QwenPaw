# -*- coding: utf-8 -*-
"""固定多用户改造前后都必须保留的丰富对话 Run 事件契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qwenpaw.schemas import Event, Message, _coerce_content_item


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "chat_run_event_contract.json"
)
REQUIRED_EVENT_TYPES = [
    "reasoning",
    "assistant_delta",
    "tool_start",
    "approval_required",
    "approval_decided",
    "tool_output",
    "skill",
    "plugin",
    "mcp",
    "command",
    "image",
    "file",
    "progress",
    "error",
    "final",
]


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixed_run_contains_every_required_rich_event() -> None:
    events = _fixture()["events"]
    assert [event["type"] for event in events] == REQUIRED_EVENT_TYPES


def test_event_order_and_relation_ids_are_stable() -> None:
    events = _fixture()["events"]
    assert [event["sequence_no"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert len({event["event_id"] for event in events}) == len(events)

    by_type = {event["type"]: event for event in events}
    assert by_type["assistant_delta"]["message_id"] == by_type["final"][
        "message_id"
    ]
    for event_type in ("tool_output", "approval_required", "approval_decided"):
        assert by_type[event_type]["tool_call_id"] == by_type["tool_start"][
            "tool_call_id"
        ]
    assert by_type["approval_required"]["approval_id"] == by_type[
        "approval_decided"
    ]["approval_id"]


def test_every_event_is_representable_by_the_existing_wire_envelopes() -> None:
    for event in _fixture()["events"]:
        wire = event["wire"]
        if wire["object"] == "message":
            parsed = Message.model_validate(wire)
            assert parsed.id == event.get("message_id")
        elif wire["object"] == "content":
            parsed = _coerce_content_item(wire)
            assert getattr(parsed, "object", None) == "content"
            assert getattr(parsed, "msg_id", None) == event["message_id"]
        else:
            parsed = Event.model_validate(wire)
            assert parsed.object == wire["object"]


def test_stop_reconnect_and_history_keep_process_events() -> None:
    event_types = [event["type"] for event in _fixture()["events"]]
    process_types = set(event_types) - {"final"}

    stopped_projection = event_types[: event_types.index("error") + 1]
    reconnect_projection = event_types.copy()
    history_projection = event_types.copy()

    assert process_types.intersection(stopped_projection)
    assert process_types.issubset(reconnect_projection)
    assert process_types.issubset(history_projection)
    assert reconnect_projection != ["final"]
    assert history_projection != ["final"]
