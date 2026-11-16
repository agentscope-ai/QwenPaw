# -*- coding: utf-8 -*-
"""SSE content events must hide scaffolding, not only headlines."""

import json
from typing import Any

from qwenpaw.app.channels.base import BaseChannel


class _ContentEvent:
    """Minimal stand-in for a content event as the channel sees it."""

    object = "content"

    def __init__(
        self,
        text: str,
        *,
        delta: bool = True,
        msg_id: str = "m1",
        index: int = 0,
    ) -> None:
        self.text = text
        self.delta = delta
        self.msg_id = msg_id
        self.index = index

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "object": self.object,
            "delta": self.delta,
            "msg_id": self.msg_id,
            "index": self.index,
            "text": self.text,
        }

    def model_dump_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)


def _channel() -> BaseChannel:
    # The SSE helpers only touch static methods, so skip __init__.
    return object.__new__(BaseChannel)


def _text_of(raw: str) -> str:
    return json.loads(raw).get("text", "")


def test_sse_deltas_hide_a_thinking_block_split_across_events() -> None:
    channel = _channel()
    states: dict[str, Any] = {}
    chunks = ("<thin", "king>secret plan", "</thin", "king>the answer")

    visible = "".join(
        _text_of(
            channel._serialize_event_for_sse(_ContentEvent(chunk), states),
        )
        for chunk in chunks
    )

    assert visible == "the answer"
    assert states == {}


def test_sse_whole_message_event_hides_scaffolding() -> None:
    channel = _channel()

    raw = channel._serialize_event_for_sse(
        _ContentEvent(
            "<thinking>secret</thinking>visible answer",
            delta=False,
        ),
        {},
    )

    assert _text_of(raw) == "visible answer"


def test_sse_flush_releases_pending_scaffold_prefix() -> None:
    channel = _channel()
    states: dict[str, Any] = {}

    _text_of(
        channel._serialize_event_for_sse(_ContentEvent("compare <"), states),
    )
    flushed = [
        _text_of(item)
        for item in BaseChannel._flush_headline_stream_states(states)
    ]

    assert "".join(flushed) == "<"
    assert states == {}
