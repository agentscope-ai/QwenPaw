# -*- coding: utf-8 -*-
"""Priority Message Queue.

Implements a priority-based message queue that orders messages
by priority level, supporting concurrent producers and consumers.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional

from agentscope.message import Msg

from .priority import MessagePriority
from .task import Task

logger = logging.getLogger(__name__)


class QueueEmpty(Exception):
    """Raised when trying to get from an empty queue."""

    pass


class QueueFull(Exception):
    """Raised when trying to put to a full queue."""

    pass


@dataclass
class QueueStats:
    """Statistics about the queue state."""

    critical: int = 0
    high: int = 0
    normal: int = 0
    low: int = 0
    total: int = 0

    @property
    def pending_high_priority(self) -> int:
        """Count of HIGH and CRITICAL items."""
        return self.critical + self.high


class PriorityMessageQueue:
    """Priority-based message queue.

    Supports priority ordering with:
    - CRITICAL > HIGH > NORMAL > LOW
    - Async put/get with optional timeout
    - Thread-safe with asyncio locks

    Features:
    - Max capacity limit
    - Blocking and non-blocking operations
    - Statistics for monitoring
    - Support for re-queueing Task objects

    Example:
        >>> queue = PriorityMessageQueue()
        >>> await queue.put(message, MessagePriority.HIGH)
        >>> task = await queue.get()
    """

    def __init__(self, maxsize: int = 0) -> None:
        """Initialize the priority queue.

        Args:
            maxsize: Maximum total items across all priorities.
                     0 means unlimited.
        """
        self._queues: Dict[MessagePriority, asyncio.Queue] = {
            MessagePriority.CRITICAL: asyncio.Queue(),
            MessagePriority.HIGH: asyncio.Queue(),
            MessagePriority.NORMAL: asyncio.Queue(),
            MessagePriority.LOW: asyncio.Queue(),
        }
        self._lock = asyncio.Lock()
        self._maxsize = maxsize
        self._total_items = 0
        # Use Condition for proper wait/notify semantics
        self._not_empty = asyncio.Condition(self._lock)
        self._not_full = asyncio.Condition(self._lock)

    def _has_space(self) -> bool:
        """Check if queue has space for new items."""
        return self._maxsize == 0 or self._total_items < self._maxsize

    def _has_items(self) -> bool:
        """Check if queue has any items."""
        return self._total_items > 0

    async def put(
        self,
        message: Msg,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout: Optional[float] = None,
    ) -> Task:
        """Add a message to the queue with the specified priority.

        Args:
            message: The message to queue.
            priority: Priority level for the message.
            timeout: Optional timeout in seconds. None means wait forever.

        Returns:
            Task object wrapping the message.

        Raises:
            QueueFull: If the queue is at capacity and timeout is None.
            asyncio.TimeoutError: If timeout expires waiting for space.
        """
        task = Task(message=message, priority=int(priority))

        async with self._not_full:
            # Wait for space if at capacity
            while not self._has_space():
                if timeout is None:
                    raise QueueFull(
                        f"Queue at capacity ({self._maxsize})"
                    )
                try:
                    await asyncio.wait_for(
                        self._not_full.wait(),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    raise QueueFull(
                        f"Queue still at capacity after {timeout}s"
                    )

            await self._queues[priority].put(task)
            self._total_items += 1
            # Notify waiting consumers
            self._not_empty.notify()

            logger.debug(
                f"Queued task {task.task_id} with priority {priority.name}"
            )
            return task

    async def put_task(self, task: Task) -> None:
        """Re-queue an existing Task object (preserves task_id and metadata).

        Args:
            task: The Task object to re-queue.

        Raises:
            QueueFull: If the queue is at capacity.
        """
        async with self._not_full:
            if not self._has_space():
                raise QueueFull(
                    f"Queue at capacity ({self._maxsize})"
                )

            priority = MessagePriority(task.priority)
            await self._queues[priority].put(task)
            self._total_items += 1
            # Notify waiting consumers
            self._not_empty.notify()

            logger.debug(
                f"Re-queued task {task.task_id} with priority {priority.name}"
            )

    async def put_nowait_async(
        self,
        message: Msg,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> Task:
        """Add a message without waiting (async version with proper locking).

        Args:
            message: The message to queue.
            priority: Priority level for the message.

        Returns:
            Task object wrapping the message.

        Raises:
            QueueFull: If the queue is at capacity.
        """
        async with self._not_full:
            if not self._has_space():
                raise QueueFull(f"Queue at capacity ({self._maxsize})")

            task = Task(message=message, priority=int(priority))
            await self._queues[priority].put(task)
            self._total_items += 1
            # Notify waiting consumers
            self._not_empty.notify()

            return task

    async def get(self, timeout: Optional[float] = None) -> Task:
        """Get the highest priority message from the queue.

        Checks queues in priority order (CRITICAL -> LOW),
        returning the first available message.

        Args:
            timeout: Optional timeout in seconds. None means wait forever.

        Returns:
            Highest priority Task available.

        Raises:
            QueueEmpty: If no message is available within timeout.
        """
        async with self._not_empty:
            # Use loop to handle spurious wakeups and race conditions
            while True:
                # Check if any queue has items
                for priority in MessagePriority:
                    queue = self._queues[priority]
                    if not queue.empty():
                        task = queue.get_nowait()
                        self._total_items -= 1
                        # Notify waiting producers that space is available
                        self._not_full.notify()
                        return task

                # No items available - wait or timeout
                if timeout is None:
                    await self._not_empty.wait()
                else:
                    try:
                        await asyncio.wait_for(
                            self._not_empty.wait(),
                            timeout=timeout
                        )
                        # Reset timeout - we used part of it waiting
                        # Continue loop to try getting again
                    except asyncio.TimeoutError:
                        raise QueueEmpty(
                            f"No message available within {timeout}s"
                        )

    async def get_nowait_async(self) -> Task:
        """Get message without waiting (async version with proper locking).

        Returns:
            Highest priority Task available.

        Raises:
            QueueEmpty: If no message is available.
        """
        async with self._lock:
            for priority in MessagePriority:
                queue = self._queues[priority]
                if not queue.empty():
                    task = queue.get_nowait()
                    self._total_items -= 1
                    # Notify waiting producers
                    self._not_full.notify()
                    return task

            raise QueueEmpty("All queues are empty")

    def get_stats(self) -> QueueStats:
        """Get current queue statistics.

        Returns:
            QueueStats with counts per priority level.
        """
        return QueueStats(
            critical=self._queues[MessagePriority.CRITICAL].qsize(),
            high=self._queues[MessagePriority.HIGH].qsize(),
            normal=self._queues[MessagePriority.NORMAL].qsize(),
            low=self._queues[MessagePriority.LOW].qsize(),
            total=self._total_items,
        )

    def qsize(self) -> int:
        """Return total number of items in queue."""
        return self._total_items

    def empty(self) -> bool:
        """Return True if queue is empty."""
        return self._total_items == 0

    def full(self) -> bool:
        """Return True if queue is at capacity."""
        return self._maxsize > 0 and self._total_items >= self._maxsize

    async def clear(self) -> int:
        """Clear all items from queue.

        Returns:
            Number of items cleared.
        """
        async with self._lock:
            count = 0
            for priority in MessagePriority:
                queue = self._queues[priority]
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        count += 1
                    except asyncio.QueueEmpty:
                        break
            self._total_items = 0
            # Notify waiting producers
            self._not_full.notify_all()
            return count
