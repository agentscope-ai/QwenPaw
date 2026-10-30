# -*- coding: utf-8 -*-
"""SSE channel tests; durable task lifecycle is covered by test_task_store."""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch


from qwenpaw.pawapp import task as task_mod
from qwenpaw.pawapp.task import SSEChannel


def _payload(text: str = "data: ") -> dict[str, Any]:
    """Strip the SSE framing and parse the JSON body."""
    return json.loads(text.removeprefix("data: ").strip())


async def _drain(channel: SSEChannel, limit: int = 20) -> list[str]:
    """Collect channel output until it ends (bounded for safety)."""
    events: list[str] = []
    async for event in channel:
        events.append(event)
        if len(events) >= limit:
            break
    return events


# ---------------------------------------------------------------------------
# SSEChannel
# ---------------------------------------------------------------------------


class TestSSEChannelSendAndClose:
    async def test_event_is_serialised_as_sse_data(self):
        channel = SSEChannel()
        await channel.send_event({"type": "progress", "step": 1})
        channel.close()

        events = await _drain(channel)

        assert len(events) == 1
        assert events[0].startswith("data: ")
        assert events[0].endswith("\n\n")
        assert _payload(events[0]) == {"type": "progress", "step": 1}

    async def test_unicode_is_not_escaped(self):
        channel = SSEChannel()
        await channel.send_event({"text": "泰哥"})
        channel.close()

        events = await _drain(channel)

        assert "泰哥" in events[0]

    async def test_send_after_close_is_dropped(self):
        channel = SSEChannel()
        channel.close()
        await channel.send_event({"type": "late"})

        assert channel.is_closed is True
        # Only the close sentinel is queued; no data event follows.
        assert await _drain(channel) == []

    async def test_full_buffer_drops_event_without_raising(self):
        channel = SSEChannel(max_buffer=1)
        await channel.send_event({"n": 1})
        await channel.send_event({"n": 2})  # buffer full -> dropped
        channel.close()

        events = await _drain(channel)

        assert [_payload(e) for e in events] == [{"n": 1}]

    async def test_close_on_full_buffer_is_swallowed(self):
        channel = SSEChannel(max_buffer=1)
        await channel.send_event({"n": 1})

        channel.close()  # sentinel cannot be queued; must not raise

        assert channel.is_closed is True

    async def test_close_unblocks_waiting_consumer(self):
        channel = SSEChannel()
        collected: list[str] = []

        async def consumer():
            async for event in channel:
                collected.append(event)

        worker = asyncio.create_task(consumer())
        await asyncio.sleep(0)
        await channel.send_event({"type": "one"})
        channel.close()
        await asyncio.wait_for(worker, timeout=5)

        assert [_payload(e) for e in collected] == [{"type": "one"}]

    async def test_closed_and_empty_channel_ends_iteration(self):
        channel = SSEChannel()
        channel.close()
        # Drain the sentinel so the queue is empty and closed.
        await _drain(channel)

        assert await _drain(channel) == []

    async def test_idle_channel_emits_keepalive_then_stops(self):
        channel = SSEChannel()
        real_wait_for = asyncio.wait_for
        calls = {"n": 0}

        async def fake_wait_for(awaitable, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # Cancel the pending get so no task is left dangling.
                awaitable.close()
                raise asyncio.TimeoutError
            return await real_wait_for(awaitable, timeout=1)

        with patch.object(task_mod.asyncio, "wait_for", fake_wait_for):
            await channel.send_event({"type": "after-keepalive"})
            channel.close()
            events = await _drain(channel)

        assert events[0] == ": keepalive\n\n"
        assert _payload(events[1]) == {"type": "after-keepalive"}

    async def test_sentinel_is_not_yielded_as_an_event(self):
        channel = SSEChannel()
        channel.close()

        events = await _drain(channel)

        assert events == []

    def test_is_closed_defaults_to_false(self):
        assert SSEChannel().is_closed is False

    async def test_multiple_events_keep_order(self):
        channel = SSEChannel()
        for index in range(5):
            await channel.send_event({"n": index})
        channel.close()

        events = await _drain(channel)

        assert [_payload(e)["n"] for e in events] == [0, 1, 2, 3, 4]
