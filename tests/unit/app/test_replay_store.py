# -*- coding: utf-8 -*-
"""Functional tests for ``qwenpaw.app.replay_store.ReplayStore``."""

from __future__ import annotations

import json
from typing import Any

import pytest

from qwenpaw.app.replay_store import RECONNECT_REQUIRED_SSE, ReplayStore
from qwenpaw.schemas import ContentType, TextContent


def _sse(payload: dict[str, Any], *, spaced: bool = False) -> str:
    """Serialize one payload as an SSE event."""
    separators = None if spaced else (",", ":")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=separators,
    )
    return f"data: {encoded}\n\n"


def _content(
    msg_id: str | None,
    text: str,
    *,
    delta: bool = True,
    sequence_number: int | None = None,
    spaced: bool = False,
) -> str:
    """Build one text-content SSE event in schema field order."""
    payload: dict[str, Any] = {
        "type": "text",
        "delta": delta,
        "index": 0,
        "status": "in_progress",
        "object": "content",
        "msg_id": msg_id,
        "text": text,
    }
    if sequence_number is not None:
        payload["sequence_number"] = sequence_number
    return _sse(payload, spaced=spaced)


def _message(
    message_id: str,
    content: list[Any],
    **extra: Any,
) -> str:
    """Build one message snapshot with ``id`` as its leading key."""
    payload = {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "content": content,
        "status": "completed",
        **extra,
        "object": "message",
    }
    return _sse(payload)


def _decode(sse: str) -> dict[str, Any]:
    """Decode one framed SSE event."""
    return json.loads(sse[len("data: ") : -2])


def _fold(*events: str) -> list[str]:
    """Append ``events`` and return the folded replay."""
    store = ReplayStore()
    for event in events:
        store.append(event)
    return list(store.replay())


def test_real_schema_field_order_keeps_content_foldable() -> None:
    """Schema fields needed for folding precede the unbounded text."""
    first = TextContent(
        type=ContentType.TEXT,
        text="a" * 300,
        delta=True,
        index=0,
        msg_id="message-a",
    )
    second = TextContent(
        type=ContentType.TEXT,
        text="b",
        delta=True,
        index=0,
        msg_id="message-a",
    )

    folded = _fold(
        f"data: {first.model_dump_json()}\n\n",
        f"data: {second.model_dump_json()}\n\n",
    )

    assert len(folded) == 1
    assert _decode(folded[0])["text"] == f"{'a' * 300}b"


@pytest.mark.parametrize("spaced", [False, True])
def test_text_deltas_merge_by_key(spaced: bool) -> None:
    """Text fragments merge without crossing message boundaries."""
    folded = _fold(
        _content("message-a", "hello ", spaced=spaced),
        _content("message-b", "other", spaced=spaced),
        _content(
            "message-a",
            "world",
            sequence_number=7,
            spaced=spaced,
        ),
    )

    decoded = [_decode(event) for event in folded]
    assert [(item["msg_id"], item["text"]) for item in decoded] == [
        ("message-b", "other"),
        ("message-a", "hello world"),
    ]
    assert decoded[-1]["sequence_number"] == 7


def test_data_arguments_keep_fields_from_the_first_fragment() -> None:
    """Merged tool arguments retain call identity from the first delta."""
    first = _sse(
        {
            "type": "data",
            "delta": True,
            "index": 0,
            "status": "in_progress",
            "object": "content",
            "msg_id": "message-a",
            "data": {
                "call_id": "call-a",
                "name": "shell",
                "arguments": '{"command":',
            },
        },
    )
    second = _sse(
        {
            "type": "data",
            "delta": True,
            "index": 0,
            "status": "in_progress",
            "object": "content",
            "msg_id": "message-a",
            "data": {"arguments": '"pwd"}'},
        },
    )

    folded = _fold(first, second)

    assert len(folded) == 1
    assert _decode(folded[0])["data"] == {
        "call_id": "call-a",
        "name": "shell",
        "arguments": '{"command":"pwd"}',
    }


def test_latest_snapshot_replaces_and_reorders_its_slot() -> None:
    """A replacement keeps the latest value at its latest position."""
    first_a = _message("message-a", [])
    message_b = _message("message-b", [])
    latest_a = _message(
        "message-a",
        [{"text": "done"}],
        metadata={"clear_history": True},
    )

    folded = _fold(first_a, message_b, latest_a)

    assert [_decode(event)["id"] for event in folded] == [
        "message-b",
        "message-a",
    ]
    assert folded[-1] == latest_a


def test_delta_after_snapshot_opens_a_new_slot() -> None:
    """A delta after a snapshot remains a separate content item."""
    snapshot = _content("message-a", "snapshot", delta=False)

    folded = _fold(
        snapshot,
        _content("message-a", "a"),
        _content("message-a", "b"),
    )

    assert folded[0] == snapshot
    assert _decode(folded[1])["text"] == "ab"


def test_control_and_invalid_events_pass_through_verbatim() -> None:
    """Events outside the fold contract retain their bytes and order."""
    control = 'data: {"type": "turn_usage", "tokens": 3}\n\n'
    invalid = "data: not-json\n\n"

    folded = _fold(
        _content("message-a", "a"),
        control,
        invalid,
        _content("message-a", "b"),
    )

    assert folded[:2] == [control, invalid]
    assert _decode(folded[-1])["text"] == "ab"


def test_null_message_id_is_dropped_without_affecting_real_key() -> None:
    """An unowned terminal snapshot cannot evict real message content."""
    unowned = _sse(
        {
            "type": "data",
            "delta": False,
            "index": 0,
            "status": "completed",
            "object": "content",
            "msg_id": None,
            "data": {"output": "ignored"},
        },
    )

    folded = _fold(
        _content("message-a", "hello "),
        unowned,
        _content("message-a", "world"),
    )

    assert len(folded) == 1
    assert _decode(folded[0])["text"] == "hello world"


def test_unsupported_delta_is_retained_instead_of_lost() -> None:
    """A classified delta with no appendable field stays verbatim."""
    unsupported = _sse(
        {
            "type": "data",
            "delta": True,
            "index": 0,
            "status": "in_progress",
            "object": "content",
            "msg_id": "message-a",
            "data": {"value": 1},
        },
    )

    assert _fold(unsupported) == [unsupported]


def test_replay_is_repeatable() -> None:
    """Reading a replay does not consume the retained events."""
    store = ReplayStore()
    store.append(_content("message-a", "text"))

    assert list(store.replay()) == list(store.replay())


def test_replay_limit_requires_history_resync() -> None:
    """An oversized replay is released instead of growing without bound."""
    store = ReplayStore(max_bytes=8, max_slots=10)

    store.append("unframed replay payload")

    assert store.requires_resync is True
    assert store.approx_bytes() == 0
    assert list(store.replay()) == [RECONNECT_REQUIRED_SSE]
