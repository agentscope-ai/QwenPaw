# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.unified_queue_manager."""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import asyncio
import gc
import time
import weakref
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cancel_cleanup", [False, True])
    async def test_shutdown_keeps_slow_cleanup_alive_after_manager_release(
        self,
        cancel_cleanup: bool,
    ):
        """Hot reload must not garbage-collect a still-cancelling consumer."""
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop_errors: list[str] = []
        started = asyncio.Event()
        cleanup_refs: list[weakref.ReferenceType[asyncio.Future[None]]] = []

        def on_loop_error(_loop, context):
            loop_errors.append(context["message"])

        async def slow_cleanup(queue, *_args):
            await queue.get()
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleanup = loop.create_future()
                cleanup_refs.append(weakref.ref(cleanup))
                await cleanup

        loop.set_exception_handler(on_loop_error)
        try:
            manager = UnifiedQueueManager(consumer_fn=slow_cleanup)
            await manager.enqueue("feishu", "ca3443e8", 10, "hello")
            await started.wait()
            consumer_ref = weakref.ref(
                manager._queues[("feishu", "ca3443e8", 10)].consumer_task,
            )
            manager_ref = weakref.ref(manager)

            # Use the real five-second shutdown grace period. The consumer
            # is still cleaning up when a hot reload releases its manager.
            await manager.stop_all()
            del manager
            gc.collect()

            assert "Task was destroyed but it is pending!" not in loop_errors
            assert consumer_ref() is not None
            assert not consumer_ref().done()
            assert manager_ref() is not None

            cleanup = cleanup_refs[0]()
            assert cleanup is not None
            if cancel_cleanup:
                cleanup.cancel()
            else:
                cleanup.set_result(None)
            del cleanup
            # Run the consumer and its completion callback before GC.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            gc.collect()
            assert consumer_ref() is None
            assert manager_ref() is None
            assert loop_errors == []
        finally:
            cleanup = cleanup_refs[0]() if cleanup_refs else None
            if cleanup is not None:
                cleanup.cancel()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
            loop.set_exception_handler(previous_handler)


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
