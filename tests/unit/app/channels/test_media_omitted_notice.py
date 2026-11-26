# -*- coding: utf-8 -*-
"""Tests for the user-facing media-omission notice."""

from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.schemas import RunStatus


def _event(metadata):
    return SimpleNamespace(metadata=metadata)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"qwenpaw_media_omitted": {"count": 3, "reason": "media limit"}},
            "3 media item(s) did not reach the model (media limit). "
            "The original files are still available.",
        ),
        (
            {"metadata": {"qwenpaw_media_omitted": {"count": 1}}},
            "1 media item(s) did not reach the model. "
            "The original files are still available.",
        ),
        ({"qwenpaw_media_omitted": {"count": 0}}, ""),
        ({"qwenpaw_media_omitted": {"count": -2}}, ""),
        ({"qwenpaw_media_omitted": {"count": True}}, ""),
        ({"qwenpaw_media_omitted": {"reason": "media limit"}}, ""),
        ({"qwenpaw_media_omitted": "3"}, ""),
        ({"qwenpaw_model_fallbacks": []}, ""),
        ({}, ""),
    ],
)
def test_media_omitted_notice(metadata, expected):
    assert BaseChannel._media_omitted_notice(_event(metadata)) == expected


def test_media_omitted_notice_accepts_message_wrapper():
    event = SimpleNamespace(
        metadata=None,
        message=SimpleNamespace(
            metadata={"qwenpaw_media_omitted": {"count": 2, "reason": "x"}},
        ),
    )
    assert BaseChannel._media_omitted_notice(event) == (
        "2 media item(s) did not reach the model (x). "
        "The original files are still available."
    )


@pytest.mark.asyncio
async def test_a_thinking_block_does_not_duplicate_the_omission_notice() -> None:
    """One omission produces exactly one notice for the turn.

    A reply with a thinking block emits two completed messages. Each one
    carried the same ``qwenpaw_media_omitted`` metadata, so channel
    delivery sent the notice twice.
    """
    channel = object.__new__(BaseChannel)
    channel.channel = "qq"
    sent: list[str] = []

    async def send_content_parts(to_handle, parts, meta):
        sent.extend(part.text for part in parts)

    channel.send_content_parts = send_content_parts
    notice = {"count": 1, "reason": "provider media limit"}
    thinking = SimpleNamespace(
        metadata={"qwenpaw_media_omitted": dict(notice)},
    )
    final = SimpleNamespace(metadata={"qwenpaw_media_omitted": dict(notice)})
    dispatched: dict = {}

    await channel._send_model_fallback_notice(
        "handle",
        thinking,
        {},
        dispatched=dispatched,
    )
    await channel._send_model_fallback_notice(
        "handle",
        final,
        {},
        dispatched=dispatched,
    )

    assert len(sent) == 1
    assert "1 media item(s) did not reach the model" in sent[0]


@pytest.mark.asyncio
async def test_send_event_sends_one_notice_for_a_turn() -> None:
    """Direct dispatch shares the turn-scoped state.

    One reply emits a thinking block and the final text as two completed
    messages. ``send_event`` has no process loop of its own, so without the
    caller passing the same mapping the notice is sent twice.
    """
    channel = object.__new__(BaseChannel)
    channel.channel = "qq"
    sent: list[str] = []

    async def send_message_content(to_handle, event, meta):
        return None

    async def send_content_parts(to_handle, parts, meta):
        sent.extend(part.text for part in parts)

    channel.send_message_content = send_message_content
    channel.send_content_parts = send_content_parts
    notice = {"count": 1, "reason": "provider media limit"}
    thinking = SimpleNamespace(
        object="message",
        status=RunStatus.Completed,
        metadata={"qwenpaw_media_omitted": dict(notice)},
    )
    final = SimpleNamespace(
        object="message",
        status=RunStatus.Completed,
        metadata={"qwenpaw_media_omitted": dict(notice)},
    )
    dispatched: dict = {}

    await channel.send_event(
        user_id="u",
        session_id="s",
        event=thinking,
        dispatched=dispatched,
    )
    await channel.send_event(
        user_id="u",
        session_id="s",
        event=final,
        dispatched=dispatched,
    )

    assert len(sent) == 1

    # A later turn brings its own mapping and must be able to notify again.
    await channel.send_event(
        user_id="u",
        session_id="s",
        event=final,
        dispatched={},
    )
    assert len(sent) == 2
