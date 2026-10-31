# -*- coding: utf-8 -*-
"""Unified queue manager with per-session priority queues.

This module implements the core queue management system using a three-tuple
QueueKey: (channel_id, session_id, priority_level). It enables:

1. Concurrent processing for different sessions
2. Concurrent processing for different priority levels within the same session
3. Strict serialization for messages with the same QueueKey
4. On-demand consumer creation (no fixed worker pools)
5. Automatic cleanup of idle queues

Architecture:
    - QueueKey = (channel_id, session_id, priority_level)
    - Each QueueKey has its own asyncio.Queue and consumer asyncio.Task
    - Consumers are created on-demand when first message arrives
    - Idle queues are automatically cleaned up after timeout
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, Tuple

logger = logging.getLogger(__name__)

# Type alias for queue key
QueueKey = Tuple[str, str, int]  # (channel_id, session_id, priority_level)

# Consumer function signature: (queue, channel_id, session_id, priority)
# Must be an async function (coroutine)
ConsumerFn = Callable[
    [asyncio.Queue, str, str, int],
    Coroutine[Any, Any, None],
]


@dataclass(frozen=True)
class EnqueueResult:
    """A determinate admission result; accepted means queue.put completed."""

    accepted: bool
    reason_code: str | None = None
    retryable: bool = False


class _AdmissionQueue(asyncio.Queue):
    def __init__(self, maxsize):
        super().__init__(maxsize=maxsize)
        self.changed = asyncio.Event()

    @property
    def unfinished(self):
        return self._unfinished_tasks

    def get_nowait(self):
        item = super().get_nowait()
        self.changed.set()
        return item


@dataclass
class QueueState:
    """State for a single queue.

    Attributes:
        queue: The asyncio.Queue for this QueueKey
        consumer_task: The asyncio.Task running the consumer
        created_at: Timestamp when queue was created
        last_activity: Timestamp of last message (enqueue or dequeue)
        processed_count: Number of messages processed
    """

    queue: asyncio.Queue
    consumer_task: asyncio.Task[None]
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    processed_count: int = 0


class UnifiedQueueManager:
    """Unified queue manager for all channels and priorities.

    Features:
    - Dynamic consumer creation: no fixed worker pools
    - Per-session + per-priority isolation
    - Automatic idle queue cleanup
    - Metrics and monitoring

    Example:
        >>> async def consumer(q, ch_id, sess_id, priority):
        ...     while True:
        ...         payload = await q.get()
        ...         # Process payload
        ...
        >>> manager = UnifiedQueueManager(consumer_fn=consumer)
        >>> manager.start_cleanup_loop()
        >>> manager.enqueue("console", "console:user1", 0, payload)
    """

    def __init__(
        self,
        consumer_fn: ConsumerFn,
        queue_maxsize: int = 1000,
        idle_timeout: float = 600.0,  # 10 minutes
        cleanup_interval: float = 60.0,  # 1 minute
    ):
        """Initialize queue manager.

        Args:
            consumer_fn: Consumer function (queue, ch_id, sess_id, priority)
            queue_maxsize: Max size per queue (0 = unbounded)
            idle_timeout: Cleanup idle queues after N seconds
            cleanup_interval: Run cleanup every N seconds
        """
        self._consumer_fn = consumer_fn
        self._queue_maxsize = queue_maxsize
        self._idle_timeout = idle_timeout
        self._cleanup_interval = cleanup_interval

        # QueueKey → QueueState
        self._queues: Dict[QueueKey, QueueState] = {}

        # Lock for thread-safe access to _queues dict
        self._lock = asyncio.Lock()

        # Cleanup task
        self._cleanup_task: asyncio.Task[None] | None = None

        # Running flag
        self._running = False
        self._closed = False

        logger.debug(
            f"UnifiedQueueManager initialized: "
            f"maxsize={queue_maxsize}, "
            f"idle_timeout={idle_timeout}s, "
            f"cleanup_interval={cleanup_interval}s",
        )

    async def enqueue(
        self,
        channel_id: str,
        session_id: str,
        priority_level: int,
        payload: Any,
    ) -> None:
        """Enqueue a message for processing.

        Args:
            channel_id: Channel identifier (e.g. "console", "feishu")
            session_id: Normalized session ID (e.g. "console:user1")
            priority_level: Priority level (0 = critical, 20 = normal)
            payload: Message payload

        Note:
            Creates queue and consumer on-demand if not exists
        """
        result = await self.admit(
            channel_id,
            session_id,
            priority_level,
            payload,
        )
        if not result.accepted:
            if result.reason_code == "QUEUE_CAPACITY_TIMEOUT":
                raise asyncio.TimeoutError
            raise RuntimeError(result.reason_code)

    async def admit(
        self,
        channel_id: str,
        session_id: str,
        priority_level: int,
        payload: Any,
        *,
        timeout: float = 30.0,
        admission_guard=None,
    ) -> EnqueueResult:
        """Wait for space, then check ownership and commit in one loop turn."""

        queue_key = (channel_id, session_id, priority_level)
        state = None

        def rejected():
            if self._closed:
                return EnqueueResult(False, "QUEUE_CLOSED", True)
            if state is not None and (
                self._queues.get(queue_key) is not state
                or state.consumer_task.done()
                or state.consumer_task.cancelling()
            ):
                return EnqueueResult(False, "QUEUE_UNAVAILABLE", True)
            return admission_guard() if admission_guard is not None else None

        try:
            async with asyncio.timeout(timeout):
                rejection = rejected()
                if rejection is not None:
                    return rejection
                state = await self._get_or_create_queue(queue_key)
                if state is None:
                    return EnqueueResult(False, "QUEUE_CLOSED", True)
                queue = state.queue
                while True:
                    rejection = rejected()
                    if rejection is not None:
                        return rejection
                    if not queue.full():
                        # asyncio.Queue.put cannot suspend when space exists.
                        await queue.put(payload)
                        state.last_activity = time.time()
                        return EnqueueResult(True)
                    queue.changed.clear()
                    await queue.changed.wait()
        except TimeoutError:
            return rejected() or EnqueueResult(
                False,
                "QUEUE_CAPACITY_TIMEOUT",
                True,
            )

    def wake_admissions(self) -> None:
        """Recheck admission guards after an owner starts stopping."""
        for state in self._queues.values():
            state.queue.changed.set()

    async def _get_or_create_queue(
        self,
        queue_key: QueueKey,
    ) -> QueueState | None:
        """Get or create queue and consumer for the given key.

        Args:
            queue_key: (channel_id, session_id, priority_level)

        Returns:
            QueueState with queue and consumer task
        """
        async with self._lock:
            if self._closed:
                return None
            # Check if already exists
            if queue_key in self._queues:
                return self._queues[queue_key]

            # Create new queue
            queue = _AdmissionQueue(maxsize=self._queue_maxsize)

            # Create consumer task
            channel_id, session_id, priority_level = queue_key
            consumer_task = asyncio.create_task(
                self._run_consumer(
                    queue,
                    channel_id,
                    session_id,
                    priority_level,
                ),
                name=(
                    f"consumer_{channel_id}_"
                    f"{session_id[:20]}_{priority_level}"
                ),
            )

            # Create state
            state = QueueState(
                queue=queue,
                consumer_task=consumer_task,
            )

            # Store state
            self._queues[queue_key] = state

            logger.info(
                f"Created queue: channel={channel_id} "
                f"session={session_id[:30]} "
                f"priority={priority_level}",
            )

            return state

    async def _run_consumer(
        self,
        queue: asyncio.Queue,
        channel_id: str,
        session_id: str,
        priority_level: int,
    ) -> None:
        """Run consumer loop for a single queue.

        Args:
            queue: The queue to consume from
            channel_id: Channel identifier
            session_id: Normalized session ID
            priority_level: Priority level

        Note:
            This loop runs until cancelled or queue is idle for cleanup
        """
        queue_key = (channel_id, session_id, priority_level)

        logger.info(
            f"Consumer started: channel={channel_id} "
            f"session={session_id[:30]} "
            f"priority={priority_level}",
        )

        try:
            # Delegate to the consumer function
            await self._consumer_fn(
                queue,
                channel_id,
                session_id,
                priority_level,
            )
        except asyncio.CancelledError:
            logger.debug(
                f"Consumer cancelled: "
                f"channel={channel_id} "
                f"session={session_id[:30]} "
                f"priority={priority_level}",
            )
            raise
        except Exception:
            logger.exception(
                f"Consumer failed: "
                f"channel={channel_id} "
                f"session={session_id[:30]} "
                f"priority={priority_level}",
            )
        finally:
            # Remove from queues dict when consumer exits
            async with self._lock:
                current = self._queues.get(queue_key)
                if (
                    current is not None
                    and current.queue is queue
                    and not queue.unfinished
                ):
                    self._queues.pop(queue_key)
                # A dead consumer may retain unfinished work. Wake blocked
                # admissions so they reject rather than fill an orphan queue.
                queue.changed.set()

            logger.info(
                f"Consumer stopped: channel={channel_id} "
                f"session={session_id[:30]} "
                f"priority={priority_level}",
            )

    def start_cleanup_loop(self) -> None:
        """Start the background cleanup task.

        Note:
            Call this after manager initialization
        """
        if self._cleanup_task is not None:
            logger.warning("Cleanup loop already running")
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(
            self._cleanup_idle_queues(),
            name="unified_queue_cleanup",
        )
        logger.info("Cleanup loop started")

    async def clear_queue(
        self,
        channel_id: str,
        session_id: str,
        priority_level: int,
    ) -> int:
        """Clear a specific queue.

        Args:
            channel_id: Channel identifier
            session_id: Session identifier
            priority_level: Priority level

        Returns:
            Number of messages cleared
        """
        queue_key = (channel_id, session_id, priority_level)
        cleared_count = 0

        async with self._lock:
            state = self._queues.get(queue_key)
            if state:
                while not state.queue.empty():
                    try:
                        state.queue.get_nowait()
                        state.queue.task_done()
                        cleared_count += 1
                    except asyncio.QueueEmpty:
                        break

        if cleared_count > 0:
            logger.info(
                f"Cleared {cleared_count} messages from queue: "
                f"channel={channel_id} session={session_id[:30]} "
                f"priority={priority_level}",
            )

        return cleared_count

    async def drain(
        self,
        channel_id: str | None = None,
        *,
        timeout: float = 5.0,
    ) -> bool:
        """Wait for accepted work, including batches already dequeued."""
        queues = [
            state.queue
            for key, state in self._queues.items()
            if channel_id is None or key[0] == channel_id
        ]
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*(queue.join() for queue in queues))
            return True
        except TimeoutError:
            return False

    async def stop_all(self) -> None:
        """Stop all consumers and cleanup task gracefully.

        Note:
            Call this during app shutdown
        """
        self._closed = True
        self._running = False
        self.wake_admissions()

        # Cancel cleanup task
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Cancel all consumer tasks
        async with self._lock:
            consumer_tasks = [
                state.consumer_task for state in self._queues.values()
            ]
            queue_count = len(self._queues)

        if consumer_tasks:
            for task in consumer_tasks:
                if not task.done() and not task.cancelling():
                    task.cancel()

            # Wait for all consumers to finish
            _, pending = await asyncio.wait(
                consumer_tasks,
                timeout=5.0,
                return_when=asyncio.ALL_COMPLETED,
            )

            if pending:
                logger.warning(
                    f"stop_all: {len(pending)} consumer(s) "
                    f"still pending after 5s",
                )

        # Keep timed-out consumers and any work they still own available for
        # a retry. Only messages never fetched by a stopped consumer can be
        # cancelled and settled here.
        async with self._lock:
            for key, state in list(self._queues.items()):
                if not state.consumer_task.done():
                    continue
                cancelled_count = 0
                while not state.queue.empty():
                    state.queue.get_nowait()
                    state.queue.task_done()
                    cancelled_count += 1
                if cancelled_count:
                    logger.info(
                        "Cancelled %s queued messages during shutdown: %s",
                        cancelled_count,
                        key,
                    )
                if not state.queue.unfinished:
                    self._queues.pop(key)
                    state.queue.changed.set()
            if self._queues:
                raise TimeoutError(
                    "Queue shutdown incomplete; retained "
                    f"{len(self._queues)} queue owner(s) for retry",
                )

        logger.info(f"Stopped all queues: total={queue_count}")

    async def _cleanup_idle_queues(self) -> None:
        """Background task to cleanup idle queues.

        Runs every cleanup_interval seconds and removes queues
        that have been empty and idle for longer than idle_timeout.
        """
        logger.info("Cleanup loop running")

        while self._running:
            try:
                await asyncio.sleep(self._cleanup_interval)

                now = time.time()
                to_cleanup: list[tuple[QueueKey, QueueState]] = []

                # Find idle queues
                async with self._lock:
                    for key, state in self._queues.items():
                        # Check if queue is empty and idle
                        if not state.queue.unfinished:
                            idle_time = now - state.last_activity
                            if idle_time > self._idle_timeout:
                                to_cleanup.append((key, state))

                # Cancel idle consumers (outside lock)
                for key, expected in to_cleanup:
                    cleanup_state: QueueState | None = None
                    async with self._lock:
                        state = self._queues.get(key)
                        if (
                            state is expected
                            and not state.queue.unfinished
                            and time.time() - state.last_activity
                            > self._idle_timeout
                        ):
                            cleanup_state = self._queues.pop(key)
                            cleanup_state.queue.changed.set()

                    if cleanup_state is not None:
                        cleanup_state.consumer_task.cancel()
                        try:
                            await cleanup_state.consumer_task
                        except asyncio.CancelledError:
                            pass

                        channel_id, session_id, priority_level = key
                        logger.info(
                            f"Cleaned up idle queue: "
                            f"channel={channel_id} "
                            f"session={session_id[:30]} "
                            f"priority={priority_level} "
                            f"processed={cleanup_state.processed_count}",
                        )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cleanup loop error")

        logger.info("Cleanup loop stopped")

    async def get_metrics(self) -> Dict[str, Any]:
        """Get queue metrics for monitoring.

        Returns:
            {
                "total_queues": int,
                "queues": [
                    {
                        "channel_id": str,
                        "session_id": str,
                        "priority_level": int,
                        "qsize": int,
                        "processed_count": int,
                        "age_seconds": float,
                        "idle_seconds": float,
                    },
                    ...
                ]
            }
        """
        now = time.time()
        queues_info = []

        async with self._lock:
            for key, state in self._queues.items():
                channel_id, session_id, priority_level = key
                queues_info.append(
                    {
                        "channel_id": channel_id,
                        "session_id": session_id,
                        "priority_level": priority_level,
                        "qsize": state.queue.qsize(),
                        "processed_count": state.processed_count,
                        "age_seconds": now - state.created_at,
                        "idle_seconds": now - state.last_activity,
                    },
                )

        return {
            "total_queues": len(queues_info),
            "queues": queues_info,
        }

    async def increment_processed(
        self,
        channel_id: str,
        session_id: str,
        priority_level: int,
        count: int = 1,
    ) -> None:
        """Increment processed count for a queue.

        Args:
            channel_id: Channel identifier
            session_id: Normalized session ID
            priority_level: Priority level
            count: Number to increment by

        Note:
            Called by consumer after processing messages
        """
        queue_key = (channel_id, session_id, priority_level)

        async with self._lock:
            state = self._queues.get(queue_key)
            if state is not None:
                state.processed_count += count
                state.last_activity = time.time()
