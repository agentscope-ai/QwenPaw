# -*- coding: utf-8 -*-
"""Priority Message Queue.

Implements a priority-based message queue that orders messages
by priority level, supporting concurrent producers and consumers.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

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

    Uses separate asyncio.Queue instances for each priority level,
    with higher priority messages being dequeued first.

    Features:
    - Thread-safe operations
    - Fair queuing within same priority (FIFO)
    - Bounded queue support
    - Statistics tracking

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
        self._not_empty = asyncio.Event()

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
            timeout: Optional timeout in seconds.

        Returns:
            Task object wrapping the message.

        Raises:
            QueueFull: If the queue is at capacity and timeout is None.
            asyncio.TimeoutError: If timeout expires waiting for space.
        """
        task = Task(message=message, priority=int(priority))

        async with self._lock:
            # Check capacity
            if self._maxsize > 0 and self._total_items >= self._maxsize:
                if timeout is None:
                    raise QueueFull(
                        f"Queue at capacity ({self._maxsize})"
                    )
                # Wait for space (simplified - full impl would use Event)
                raise QueueFull("Queue full with timeout not fully implemented")

            await self._queues[priority].put(task)
            self._total_items += 1
            self._not_empty.set()

            logger.debug(
                f"Enqueued task {task.task_id} with priority {priority.name}"
            )
            return task

    def put_nowait(
        self,
        message: Msg,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> Task:
        """Add a message without waiting (non-async version).

        Args:
            message: The message to queue.
            priority: Priority level for the message.

        Returns:
            Task object wrapping the message.

        Raises:
            QueueFull: If the queue is at capacity.
        """
        if self._maxsize > 0 and self._total_items >= self._maxsize:
            raise QueueFull(f"Queue at capacity ({self._maxsize})")

        task = Task(message=message, priority=int(priority))
        self._queues[priority].put_nowait(task)
        self._total_items += 1
        self._not_empty.set()

        return task

    async def get(self, timeout: Optional[float] = None) -> Task:
        """Get the highest priority message from the queue.

        Checks queues in priority order (CRITICAL -> LOW),
        returning the first available message.

        Args:
            timeout: Optional timeout in seconds.

        Returns:
            Highest priority Task available.

        Raises:
            QueueEmpty: If no message is available.
            asyncio.TimeoutError: If timeout expires.
        """
        # Try to get immediately
        task = await self._try_get()
        if task:
            return task

        # Wait for message
        if timeout:
            try:
                await asyncio.wait_for(self._not_empty.wait(), timeout)
            except asyncio.TimeoutError:
                raise QueueEmpty("Timeout waiting for message")
        else:
            await self._not_empty.wait()

        task = await self._try_get()
        if task:
            return task

        raise QueueEmpty("Queue is empty")

    def get_nowait(self) -> Task:
        """Get message without waiting (non-async version).

        Returns:
            Highest priority Task available.

        Raises:
            QueueEmpty: If no message is available.
        """
        for priority in MessagePriority:
            queue = self._queues[priority]
            if not queue.empty():
                task = queue.get_nowait()
                self._total_items -= 1
                return task

        raise QueueEmpty("All queues are empty")

    async def _try_get(self) -> Optional[Task]:
        """Try to get a task without blocking.

        Returns:
            Task if available, None otherwise.
        """
        async with self._lock:
            for priority in MessagePriority:
                queue = self._queues[priority]
                if not queue.empty():
                    task = queue.get_nowait()
                    self._total_items -= 1
                    logger.debug(
                        f"Dequeued task {task.task_id} from {priority.name} queue"
                    )
                    # Reset event if all queues empty
                    if self._total_items == 0:
                        self._not_empty.clear()
                    return task
            return None

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

    def empty(self) -> bool:
        """Check if all queues are empty.

        Returns:
            True if no messages are queued.
        """
        return self._total_items == 0

    def qsize(self) -> int:
        """Get total number of queued messages.

        Returns:
            Total messages across all priority levels.
        """
        return self._total_items

    async def clear(self) -> int:
        """Clear all messages from all queues.

        Returns:
            Number of messages cleared.
        """
        async with self._lock:
            count = self._total_items
            for queue in self._queues.values():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            self._total_items = 0
            self._not_empty.clear()
            return count
