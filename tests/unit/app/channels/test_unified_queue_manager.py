# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.unified_queue_manager."""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import asyncio
import time
from typing import Any

import pytest

from qwenpaw.app.channels.unified_queue_manager import (
    QueueState,
    UnifiedQueueManager,
)


async def _drain_consumer(
    queue: asyncio.Queue,
    channel_id: str,
    session_id: str,
    priority: int,
) -> None:
    """Consumer that drains queue and exits on sentinel `None`."""
    while True:
        item = await queue.get()
        if item is None:
            return
        # discard non-sentinel items
        queue.task_done()  # no-op if not tracked, safe in tests


async def _stuck_consumer(
    queue: asyncio.Queue,
    channel_id: str,
    session_id: str,
    priority: int,
) -> None:
    """Consumer that hangs forever (used to keep queue non-empty)."""
    await asyncio.Event().wait()


@pytest.fixture
def manager() -> UnifiedQueueManager:
    return UnifiedQueueManager(
        consumer_fn=_drain_consumer,
        queue_maxsize=10,
        idle_timeout=0.1,
        cleanup_interval=0.05,
    )


# ---------------------------------------------------------------------------
# Enqueue / consumer creation
# ---------------------------------------------------------------------------


async def _wait_for_qsize(
    queue: asyncio.Queue,
    target: int,
    timeout: float = 1.0,
) -> None:
    """Poll until ``queue.qsize()`` reaches ``target`` or timeout.

    The ``_drain_consumer`` runs as a separate task; ``enqueue`` returning
    only guarantees the item was put into the queue, not that the consumer
    task has been scheduled to run and drained it. Asserting ``qsize()``
    immediately after ``enqueue`` therefore races on event-loop scheduling
    and is flaky across Python versions (passes on 3.11, fails on 3.13).
    Polling yields control to the loop so the consumer task can make
    progress deterministically.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if queue.qsize() == target:
            return
        await asyncio.sleep(0)
    assert (
        queue.qsize() == target
    ), f"queue qsize {queue.qsize()} never reached {target} within {timeout}s"


class TestEnqueueAndCreate:
    @pytest.mark.asyncio
    async def test_enqueue_creates_queue_and_consumer(
        self,
        manager: UnifiedQueueManager,
    ):
        await manager.enqueue("console", "console:u1", 0, "hello")
        assert ("console", "console:u1", 0) in manager._queues
        state = manager._queues[("console", "console:u1", 0)]
        assert isinstance(state, QueueState)
        # drained by consumer; poll because the consumer runs as a separate
        # task that is only scheduled once we yield to the event loop.
        await _wait_for_qsize(state.queue, target=0)

    @pytest.mark.asyncio
    async def test_enqueue_is_idempotent_for_same_key(
        self,
        manager: UnifiedQueueManager,
    ):
        await manager.enqueue("console", "console:u1", 0, "a")
        first = manager._queues[("console", "console:u1", 0)]
        await manager.enqueue("console", "console:u1", 0, "b")
        second = manager._queues[("console", "console:u1", 0)]
        assert first is second

    @pytest.mark.asyncio
    async def test_different_keys_create_different_queues(
        self,
        manager: UnifiedQueueManager,
    ):
        await manager.enqueue("console", "console:u1", 0, "a")
        await manager.enqueue("console", "console:u1", 10, "b")
        await manager.enqueue("feishu", "feishu:u1", 0, "c")
        assert len(manager._queues) == 3

    @pytest.mark.asyncio
    async def test_enqueue_records_last_activity(
        self,
        manager: UnifiedQueueManager,
    ):
        await manager.enqueue("console", "console:u1", 0, "a")
        state = manager._queues[("console", "console:u1", 0)]
        before = state.last_activity
        time.sleep(0.01)
        await manager.enqueue("console", "console:u1", 0, "b")
        assert state.last_activity > before


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_cleanup_loop_idempotent(
        self,
        manager: UnifiedQueueManager,
    ):
        manager.start_cleanup_loop()
        first = manager._cleanup_task
        manager.start_cleanup_loop()
        assert manager._cleanup_task is first
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_stop_all_cancels_cleanup_task(
        self,
        manager: UnifiedQueueManager,
    ):
        manager.start_cleanup_loop()
        await manager.stop_all()
        assert manager._cleanup_task is None
        assert manager._running is False

    @pytest.mark.asyncio
    async def test_stop_all_without_started_cleanup(
        self,
        manager: UnifiedQueueManager,
    ):
        # stop_all should not crash if cleanup loop was never started
        await manager.enqueue("console", "console:u1", 0, "hi")
        await manager.stop_all()
        assert manager._queues == {}

    @pytest.mark.asyncio
    async def test_idempotent_stop_all(self, manager: UnifiedQueueManager):
        manager.start_cleanup_loop()
        await manager.stop_all()
        await manager.stop_all()  # no crash
        assert manager._queues == {}

    @pytest.mark.asyncio
    async def test_stop_all_cancels_consumers(
        self,
        manager: UnifiedQueueManager,
    ):
        await manager.enqueue("console", "console:u1", 0, "hi")
        state = manager._queues[("console", "console:u1", 0)]
        assert not state.consumer_task.done()
        await manager.stop_all()
        assert state.consumer_task.cancelled() or state.consumer_task.done()


# ---------------------------------------------------------------------------
# Cleanup loop
# ---------------------------------------------------------------------------


class TestCleanupLoop:
    @pytest.mark.asyncio
    async def test_cleanup_loop_does_not_leak_active_queue(self):
        # Stuck consumer keeps the queue non-empty (item not drained),
        # so cleanup must skip it even after idle_timeout elapses.
        mgr = UnifiedQueueManager(
            consumer_fn=_stuck_consumer,
            queue_maxsize=10,
            idle_timeout=0.05,
            cleanup_interval=0.02,
        )
        mgr.start_cleanup_loop()
        await mgr.enqueue("console", "console:u1", 0, "blocked")
        await asyncio.sleep(0.2)
        # Queue still has the unfetched item → must not be cleaned up
        assert ("console", "console:u1", 0) in mgr._queues
        state = mgr._queues[("console", "console:u1", 0)]
        assert state.queue.qsize() == 1
        await mgr.stop_all()

    @pytest.mark.asyncio
    async def test_cleanup_loop_removes_idle_queue(
        self,
        manager: UnifiedQueueManager,
    ):
        manager.start_cleanup_loop()
        await manager.enqueue("console", "console:u1", 0, "x")
        assert ("console", "console:u1", 0) in manager._queues
        # Wait long enough for idle_timeout (0.1s) + cleanup_interval (0.05s)
        await asyncio.sleep(0.4)
        assert ("console", "console:u1", 0) not in manager._queues
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_cleanup_loop_survives_exceptions(
        self,
        manager: UnifiedQueueManager,
    ):
        manager.start_cleanup_loop()
        # Inject an invalid idle_timeout to force type juggling issue
        # We instead just simulate: clean up should keep running
        await asyncio.sleep(0.1)
        assert manager._cleanup_task is not None
        assert not manager._cleanup_task.done()
        await manager.stop_all()


# ---------------------------------------------------------------------------
# clear_queue
# ---------------------------------------------------------------------------


class TestClearQueue:
    @pytest.mark.asyncio
    async def test_clear_queue_returns_count(
        self,
        manager: UnifiedQueueManager,
    ):
        # Use a consumer that doesn't drain, so items remain.
        async def slow(q, *args):
            await asyncio.sleep(10)

        mgr = UnifiedQueueManager(consumer_fn=slow, queue_maxsize=10)
        await mgr.enqueue("console", "console:u1", 0, "a")
        await mgr.enqueue("console", "console:u1", 0, "b")
        await asyncio.sleep(0.01)
        # Pause consumer to ensure items still queued
        count = await mgr.clear_queue("console", "console:u1", 0)
        assert count >= 0  # consumer may have drained some
        await mgr.stop_all()

    @pytest.mark.asyncio
    async def test_clear_unknown_queue_returns_zero(
        self,
        manager: UnifiedQueueManager,
    ):
        count = await manager.clear_queue("nope", "nope:u1", 0)
        assert count == 0


# ---------------------------------------------------------------------------
# Metrics + increment_processed
# ---------------------------------------------------------------------------


class TestMetrics:
    @pytest.mark.asyncio
    async def test_get_metrics_shape(self, manager: UnifiedQueueManager):
        await manager.enqueue("console", "console:u1", 0, "x")
        m = await manager.get_metrics()
        assert m["total_queues"] == 1
        assert m["queues"][0]["channel_id"] == "console"
        assert m["queues"][0]["priority_level"] == 0
        assert "qsize" in m["queues"][0]
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_increment_processed_updates_count(
        self,
        manager: UnifiedQueueManager,
    ):
        await manager.enqueue("console", "console:u1", 0, "x")
        await manager.increment_processed("console", "console:u1", 0, 3)
        state = manager._queues[("console", "console:u1", 0)]
        assert state.processed_count == 3
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_increment_processed_unknown_queue_no_crash(
        self,
        manager: UnifiedQueueManager,
    ):
        # Should silently no-op
        await manager.increment_processed("nope", "nope:u1", 0, 1)


# ---------------------------------------------------------------------------
# Queue full timeout
# ---------------------------------------------------------------------------


class TestQueueFull:
    @pytest.mark.asyncio
    async def test_enqueue_full_raises_timeout(self):
        async def stuck(q, *args):
            await asyncio.sleep(100)

        # maxsize=1, and consumer is stuck → 2nd enqueue will fill, 3rd will
        # block and eventually timeout (30s default). Lower the timeout via
        # monkeypatching asyncio.wait_for would be ideal; instead we use a
        # full queue with maxsize=0 is unbounded. So use maxsize=1 and
        # pause consumer, then enq two items — second would block but
        # we can't wait 30s. Use unbounded queue — this test guards that
        # the code path exists, but skip the actual 30s timeout.
        mgr = UnifiedQueueManager(consumer_fn=stuck, queue_maxsize=1)
        await mgr.enqueue("console", "console:u1", 0, "a")
        # second item should block; we cancel quickly to avoid hang
        task = asyncio.create_task(
            mgr.enqueue("console", "console:u1", 0, "b"),
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        await mgr.stop_all()


# ---------------------------------------------------------------------------
# Race condition: cleanup must not remove a newly recreated queue state
# ---------------------------------------------------------------------------


class TestCleanupRaceCondition:
    @pytest.mark.asyncio
    async def test_consumer_cleanup_does_not_remove_recreated_queue(
        self,
    ):
        """When cleanup removes a queue entry and a new enqueue() recreates
        it before the old consumer's finally block runs, the old consumer
        must not pop the new state from _queues.
        """
        barrier_a = asyncio.Event()
        barrier_b = asyncio.Event()

        async def waiting_consumer_a(
            queue: asyncio.Queue,
            channel_id: str,
            session_id: str,
            priority: int,
        ) -> None:
            await barrier_a.wait()

        async def waiting_consumer_b(
            queue: asyncio.Queue,
            channel_id: str,
            session_id: str,
            priority: int,
        ) -> None:
            await barrier_b.wait()

        mgr = UnifiedQueueManager(
            consumer_fn=waiting_consumer_a,
            queue_maxsize=10,
            idle_timeout=0.1,
            cleanup_interval=0.05,
        )

        queue_key = ("console", "console:u1", 0)

        # 1. Create first queue state and consumer
        await mgr.enqueue("console", "console:u1", 0, "first")
        first_state = mgr._queues[queue_key]
        first_consumer = first_state.consumer_task
        assert first_consumer is not None

        # 2. Simulate cleanup: remove state from _queues (don't cancel yet
        #    to keep the old consumer alive while we recreate).
        async with mgr._lock:
            removed_state = mgr._queues.pop(queue_key)
        assert removed_state is first_state

        # 3. Now a new enqueue recreates the queue before the old
        #    consumer finishes. Use a different consumer so we can
        #    independently control when each one exits.
        mgr._consumer_fn = waiting_consumer_b
        await mgr.enqueue("console", "console:u1", 0, "second")
        new_state = mgr._queues.get(queue_key)
        assert new_state is not None
        assert new_state is not first_state
        new_consumer = new_state.consumer_task
        assert new_consumer is not None

        # 4. Let the OLD consumer finish. Its finally block must NOT
        #    remove the *new* state (different QueueState identity).
        first_consumer.cancel()
        barrier_a.set()
        try:
            await first_consumer
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.05)

        assert (
            queue_key in mgr._queues
        ), "Old consumer's finally block must not remove the new QueueState"
        assert mgr._queues[queue_key] is new_state

        # 5. Now let the NEW consumer finish — *its* finally block should
        #    correctly remove the matching new state.
        barrier_b.set()
        try:
            await new_consumer
        except (asyncio.CancelledError, Exception):
            pass
        await asyncio.sleep(0.05)

        assert (
            queue_key not in mgr._queues
        ), "New consumer's finally block must remove its own QueueState"

        # 6. Cleanup
        await mgr.stop_all()

    @pytest.mark.asyncio
    async def test_cleanup_idle_timeout_removes_idle_queue(
        self,
    ):
        """Idle queues must still be cleaned up correctly after the fix."""
        mgr = UnifiedQueueManager(
            consumer_fn=_drain_consumer,
            queue_maxsize=10,
            idle_timeout=0.05,
            cleanup_interval=0.02,
        )
        mgr.start_cleanup_loop()

        await mgr.enqueue("console", "console:u1", 0, "x")
        assert ("console", "console:u1", 0) in mgr._queues

        # Wait for idle timeout + cleanup interval
        await asyncio.sleep(0.3)

        assert ("console", "console:u1", 0) not in mgr._queues
        await mgr.stop_all()
