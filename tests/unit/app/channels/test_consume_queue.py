# -*- coding: utf-8 -*-
"""Consumer lifecycle: handle timeout must not wedge the session queue."""

from __future__ import annotations

# pylint: disable=protected-access

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager


class _HangThenPassChannel:
    """Native-payload channel that can hang on the first handle."""

    channel = "feishu"

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.started = asyncio.Event()
        self.hang_next = True

    def _is_native_payload(self, payload: object) -> bool:
        return isinstance(payload, dict)

    async def _consume_one_request(self, payload: object) -> None:
        self.calls.append(payload)
        self.started.set()
        if self.hang_next:
            await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_handle_timeout_unblocks_later_same_queue_messages() -> None:
    """A wedged high-priority handle must not trap later messages."""
    ch = _HangThenPassChannel()
    manager = ChannelManager(channels=[ch])
    manager._handle_timeout = 0.05
    manager._handle_cancel_grace = 0.05
    qmgr = UnifiedQueueManager(
        consumer_fn=manager._consume_queue,
        queue_maxsize=10,
        idle_timeout=60.0,
        cleanup_interval=60.0,
        stuck_timeout=60.0,
        cancel_timeout=0.05,
    )
    manager._queue_manager = qmgr

    await qmgr.enqueue("feishu", "feishu:sess", 10, {"text": "card"})
    await asyncio.wait_for(ch.started.wait(), timeout=1)
    ch.hang_next = False
    ch.started.clear()
    await qmgr.enqueue("feishu", "feishu:sess", 10, {"text": "hello"})

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if any(
            isinstance(p, dict) and p.get("text") == "hello" for p in ch.calls
        ):
            break
        await asyncio.sleep(0.02)

    assert any(
        isinstance(p, dict) and p.get("text") == "hello" for p in ch.calls
    )
    await qmgr.stop_all()


@pytest.mark.asyncio
async def test_high_priority_wedge_does_not_block_normal_priority() -> None:
    """p10 hang must not prevent a new p20 consumer from being created."""
    ch = _HangThenPassChannel()
    manager = ChannelManager(channels=[ch])
    manager._handle_timeout = 30.0
    manager._handle_cancel_grace = 0.05
    qmgr = UnifiedQueueManager(
        consumer_fn=manager._consume_queue,
        queue_maxsize=10,
        idle_timeout=60.0,
        cleanup_interval=60.0,
        stuck_timeout=60.0,
    )
    manager._queue_manager = qmgr

    await qmgr.enqueue("feishu", "feishu:sess", 10, {"text": "card"})
    await asyncio.wait_for(ch.started.wait(), timeout=1)
    ch.hang_next = False
    await qmgr.enqueue("feishu", "feishu:sess", 20, {"text": "hello"})

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if ("feishu", "feishu:sess", 20) in qmgr._queues:
            break
        await asyncio.sleep(0.02)

    assert ("feishu", "feishu:sess", 10) in qmgr._queues
    assert ("feishu", "feishu:sess", 20) in qmgr._queues
    # p10 consumer is still the original wedged one; p20 is a new queue.
    p10 = qmgr._queues[("feishu", "feishu:sess", 10)]
    assert not p10.consumer_task.done()
    await qmgr.stop_all()


@pytest.mark.asyncio
async def test_steal_stale_tracker_run_stops_old_producer() -> None:
    tracker = MagicMock()
    tracker.get_run_age_seconds = AsyncMock(return_value=10_000.0)
    tracker.request_stop = AsyncMock(return_value=True)
    host = MagicMock()
    host._workspace = MagicMock(task_tracker=tracker)
    host._STALE_TRACKER_RUN_SECONDS = BaseChannel._STALE_TRACKER_RUN_SECONDS
    stolen = await BaseChannel._steal_stale_tracker_run(host, "chat-1")
    assert stolen is True
    tracker.request_stop.assert_awaited()


@pytest.mark.asyncio
async def test_steal_recent_tracker_run_is_left_alone() -> None:
    tracker = MagicMock()
    tracker.get_run_age_seconds = AsyncMock(return_value=1.0)
    tracker.request_stop = AsyncMock(return_value=True)
    host = MagicMock()
    host._workspace = MagicMock(task_tracker=tracker)
    host._STALE_TRACKER_RUN_SECONDS = BaseChannel._STALE_TRACKER_RUN_SECONDS
    stolen = await BaseChannel._steal_stale_tracker_run(host, "chat-1")
    assert stolen is False
    tracker.request_stop.assert_not_called()
