# -*- coding: utf-8 -*-
"""Verify transient notification events and successful console completion."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app import inbox_store, notification_store
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.schemas import RunStatus

pytestmark = [pytest.mark.unit, pytest.mark.p1]


@pytest.fixture(autouse=True)
def clear_events():
    """Keep the shared feed isolated between tests."""
    notification_store._EVENTS.clear()
    yield
    notification_store._EVENTS.clear()


def test_snapshots_are_non_consuming_bounded_and_expire(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(notification_store.time, f"time", lambda: clock[0])
    for number in range(510):
        notification_store.publish(
            category=f"mail",
            agent_id=f"agent-a",
            title=f"{number}",
            body=f"{'x' * 600}",
        )
    first = notification_store.snapshot()
    assert len(first) == 500
    assert first == notification_store.snapshot()
    assert len(first[0][f"body"]) == 500
    clock[0] += 301
    assert notification_store.snapshot() == []


@pytest.mark.parametrize(
    (f"category", f"status", f"body", f"expected"),
    [
        (f"memory", f"success", f"updated", 0),
        (f"heartbeat", f"success", f"HEARTBEAT_OK", 0),
        (f"heartbeat", f"success", f"", 0),
        (f"heartbeat", f"success", f"A task needs attention", 1),
        (f"heartbeat", f"error", f"", 1),
        (f"cron", f"error", f"Timeout", 1),
        (f"mail", f"success", f"New mail", 1),
    ],
)
def test_inbox_notification_policy(category, status, body, expected):
    notification_store.publish_inbox(
        {
            f"id": f"event-1",
            f"source_type": category,
            f"agent_id": f"agent-a",
            f"status": status,
            f"title": f"Result",
            f"body": body,
        },
    )
    events = notification_store.snapshot()
    assert len(events) == expected
    if events:
        assert events[0][f"inbox_event_id"] == f"event-1"


@pytest.mark.asyncio
async def test_saved_inbox_event_is_forwarded_and_can_be_found_by_id(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(inbox_store, f"_INBOX_PATH", tmp_path / f"inbox.json")
    event = await inbox_store.append_event(
        agent_id=f"agent-a",
        source_type=f"mail",
        source_id=f"mailbox",
        event_type=f"new_email",
        status=f"success",
        title=f"New mail",
        body=f"Hello",
    )
    page, total, unread = await inbox_store.query_events(
        event_id=event[f"id"],
        limit=1,
    )
    assert page == [event]
    assert (total, unread) == (1, 1)
    assert notification_store.snapshot()[0][f"id"] == event[f"id"]
    assert (await inbox_store.query_events(event_id=f"missing"))[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    f"ending",
    [f"success", f"cancel", f"error", f"failed"],
)
async def test_only_successful_console_turns_publish(ending, monkeypatch):
    channel = ConsoleChannel(
        process=MagicMock(),
        enabled=True,
        bot_prefix=f"",
    )
    channel._workspace = SimpleNamespace(
        agent_id=f"agent-a",
        chat_manager=SimpleNamespace(
            touch_chat_by_session=AsyncMock(
                return_value=SimpleNamespace(id=f"chat-1"),
            ),
        ),
    )
    request = SimpleNamespace(
        session_id=f"session-1",
        user_id=f"user-1",
        channel=f"console",
        channel_meta={},
        input=[],
    )
    response = SimpleNamespace(
        object=f"response",
        status=RunStatus.Completed,
        type=f"response",
        output=[],
    )

    async def process(_request):
        yield response
        if ending == f"cancel":
            raise asyncio.CancelledError
        if ending == f"error":
            raise RuntimeError(f"stream failed")

    monkeypatch.setattr(channel, f"_process", process)
    monkeypatch.setattr(
        channel,
        f"_serialize_event_for_sse",
        lambda *_: f"{{}}",
    )
    monkeypatch.setattr(channel, f"_clear_session_turn_usage", MagicMock())
    monkeypatch.setattr(
        channel,
        f"_commit_turn_usage",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(channel, f"_on_response_cycle_end", AsyncMock())
    monkeypatch.setattr(channel, f"_print_error", MagicMock())
    monkeypatch.setattr(
        channel,
        f"_get_response_error_message",
        lambda _: f"failed" if ending == f"failed" else f"",
    )
    if ending == f"cancel":
        with pytest.raises(asyncio.CancelledError):
            _ = [item async for item in channel.stream_one(request)]
    else:
        _ = [item async for item in channel.stream_one(request)]
    events = notification_store.snapshot()
    assert len(events) == (1 if ending == f"success" else 0)
    if events:
        assert events[0][f"session_id"] == f"chat-1"
        assert events[0][f"agent_id"] == f"agent-a"
