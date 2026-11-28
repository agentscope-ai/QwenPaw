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


@pytest.mark.parametrize("case", ["schema", "text", "data"])
def test_supported_deltas_fold_without_losing_canonical_fields(case) -> None:
    """Supported fragments fold while retaining identity fields."""
    if case == "schema":
        contents = [
            TextContent(
                type=ContentType.TEXT,
                text=text,
                delta=True,
                index=0,
                msg_id="message-a",
            )
            for text in ("a" * 300, "b")
        ]
        events = [
            f"data: {content.model_dump_json()}\n\n" for content in contents
        ]
        expected = f"{'a' * 300}b"
    elif case == "text":
        events = [
            _content("message-a", "hello ", spaced=True),
            _content("message-b", "other", spaced=True),
            _content("message-a", "world", sequence_number=7, spaced=True),
        ]
        expected = "hello world"
    else:
        common = {
            "type": "data",
            "delta": True,
            "index": 0,
            "status": "in_progress",
            "object": "content",
            "msg_id": "message-a",
        }
        events = [
            _sse(
                {
                    **common,
                    "data": {
                        "call_id": "call-a",
                        "name": "shell",
                        "arguments": '{"command":',
                    },
                },
            ),
            _sse({**common, "data": {"arguments": '"pwd"}'}}),
        ]
        expected = '{"command":"pwd"}'

    decoded = [_decode(event) for event in _fold(*events)]
    if case == "text":
        assert [(item["msg_id"], item.get("text")) for item in decoded] == [
            ("message-b", "other"),
            ("message-a", expected),
        ]
        assert decoded[-1]["sequence_number"] == 7
    elif case == "data":
        assert decoded[0]["data"] == {
            "call_id": "call-a",
            "name": "shell",
            "arguments": expected,
        }
    else:
        assert decoded[0]["text"] == expected


def test_snapshot_replaces_its_slot_and_later_delta_opens_a_new_slot() -> None:
    """Snapshots replace their slot while later deltas remain separate."""
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
    snapshot = _content("message-a", "snapshot", delta=False)

    folded = _fold(
        snapshot,
        _content("message-a", "a"),
        _content("message-a", "b"),
    )

    assert folded[0] == snapshot
    assert _decode(folded[1])["text"] == "ab"


@pytest.mark.parametrize("case", ["control", "null-id", "unsupported"])
def test_unfoldable_events_are_preserved_or_explicitly_dropped(case) -> None:
    """Unfoldable inputs follow their documented preserve/drop behavior."""
    if case == "control":
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
    elif case == "null-id":
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
        assert [_decode(event)["text"] for event in folded] == [
            "hello world",
        ]
    else:
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
