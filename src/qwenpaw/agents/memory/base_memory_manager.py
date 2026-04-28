# -*- coding: utf-8 -*-
"""Abstract base class for memory managers."""
import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agentscope.message import Msg
from agentscope.tool import ToolResponse

from ..utils.registry import Registry

logger = logging.getLogger(__name__)


class BaseMemoryManager(ABC):
    """Abstract base class for memory manager backends.

    Lifecycle:
        1. Instantiate with ``working_dir`` and ``agent_id``.
        2. ``await start()`` – initialize storage backend.
        3. Use ``summarize()``, ``memory_search()``, etc. during session.
        4. ``await close()`` – flush and release resources.

    Attributes:
        working_dir: Root directory for persisting memory files.
        agent_id: Unique identifier of the owning agent.
    """

    def __init__(self, working_dir: str, agent_id: str):
        self.working_dir: str = working_dir
        self.agent_id: str = agent_id
        self._summary_task_info: dict[str, dict[str, Any]] = {}
        self._task_counter: int = 0
        self._task_queue: asyncio.Queue[
            tuple[str, list[Msg], dict]
        ] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

        # Batch summarization: accumulate messages until threshold
        self._pending_messages: list[Msg] = []
        self._pending_token_count: int = 0
        self._summarize_threshold: int = 4000  # Default token threshold
        self._pending_lock = asyncio.Lock()

    @abstractmethod
    async def start(self) -> None:
        """Initialize the storage backend. Called once after instantiation."""

    @abstractmethod
    async def close(self) -> bool:
        """Flush pending state and release resources.

        Returns:
            ``True`` if shutdown completed cleanly.
        """

    @abstractmethod
    def get_memory_prompt(self, language: str = "zh") -> str:
        """Return the memory guidance prompt for inclusion
        in the system prompt.

        Args:
            language: Language code (``"zh"`` or ``"en"``).

        Returns:
            Formatted memory guidance string.
        """

    @abstractmethod
    def list_memory_tools(self) -> list[Callable[..., ToolResponse]]:
        """Return tool functions exposed to the agent for memory access.

        Each returned callable may have any signature but must return a
        ``ToolResponse``.  Implementations register whatever memory-related
        tools make sense for the backend (e.g. semantic search, listing).

        Returns:
            Ordered list of tool functions to register with the agent toolkit.
        """

    # pylint: disable=unused-argument
    async def summarize(self, messages: list[Msg], **kwargs) -> str:
        """Summarize conversation messages and persist to memory.

        NOTE: This method is optional. Subclasses may override this method
        to implement actual summarization. Base implementation returns empty
        string, indicating no summarization support.

        Args:
            messages: Ordered conversation messages to summarize.
            **kwargs: Implementation-specific options.

        Returns:
            Summary string, or empty string if not implemented.
        """
        return ""

    # pylint: disable=unused-argument
    async def retrieve(
        self,
        messages: list[Msg] | Msg,
        **kwargs,
    ) -> dict | None:
        """Retrieve relevant memory based on the given messages.

        NOTE: This method is optional. Subclasses may override this method
        to implement actual retrieval. Base implementation returns None,
        indicating no retrieval support or no relevant memory found.

        Args:
            messages: One or more conversation messages used as the query.
            **kwargs: Implementation-specific options.

        Returns:
            Dict with memory context to merge with kwargs, or None if
            not implemented or no relevant memory found.
        """
        return None

    # pylint: disable=unused-argument
    async def dream(self, **kwargs) -> None:
        """Optimize memory files via a background agent pass.

        NOTE: This method is optional. Subclasses may override this method
        to implement actual memory optimization. Base implementation does
        nothing, indicating no dream support.

        Runs a lightweight ReAct agent with file-editing tools to
        consolidate redundant or outdated memory entries.
        """
        return None

    def set_summarize_threshold(self, tokens: int) -> None:
        """Set the token threshold for batch summarization.
        
        Args:
            tokens: Number of tokens to accumulate before triggering summarization.
        """
        self._summarize_threshold = tokens

    async def add_summarize_task(self, messages: list[Msg], **kwargs):
        """Schedule a background summarization task with batch accumulation.
        
        Messages are accumulated until the token threshold is reached,
        then a single summarization task is triggered to reduce API calls.
        
        Args:
            messages: Messages to accumulate.
            **kwargs: Forwarded to ``summarize()``.
        """
        async with self._pending_lock:
            self._pending_messages.extend(messages)
            # Rough token estimation: ~4 chars per token for CJK/English mix
            for msg in messages:
                text = msg.get_text_content() or ""
                self._pending_token_count += len(text) // 4 + 1

            if self._pending_token_count < self._summarize_threshold:
                logger.debug(
                    f"Accumulating messages: {self._pending_token_count}/{self._summarize_threshold} tokens"
                )
                return

            # Threshold reached, trigger summarization
            batch_messages = self._pending_messages.copy()
            self._pending_messages.clear()
            self._pending_token_count = 0

        # Execute outside the lock
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._summarize_worker())

        self._task_counter += 1
        task_id = f"task_{self._task_counter}"

        self._summary_task_info[task_id] = {
            "task_id": task_id,
            "task": self._worker_task,
            "start_time": datetime.now(),
            "status": "pending",
            "result": None,
            "error": None,
        }

        self._task_queue.put_nowait((task_id, batch_messages, kwargs))
        logger.info(f"Batch summarize task {task_id} enqueued ({len(batch_messages)} messages)")

    def _update_task_statuses(self) -> None:
        """Update status for pending/running tasks if worker was cancelled."""
        if self._worker_task is None:
            return
        if not self._worker_task.done():
            return

        # Worker finished - update any running tasks
        for task_id, info in self._summary_task_info.items():
            if info["status"] == "running":
                if self._worker_task.cancelled():
                    info["status"] = "cancelled"
                    logger.info(
                        f"Summary task {task_id} cancelled (worker stopped)",
                    )
                else:
                    exc = self._worker_task.exception()
                    if exc is not None:
                        info["status"] = "failed"
                        info["error"] = str(exc)
                        logger.error(f"Summary task {task_id} failed: {exc}")

    async def _summarize_worker(self) -> None:
        """Background worker that processes summarize tasks serially."""
        while True:
            task_id, messages, kwargs = await self._task_queue.get()
            info = self._summary_task_info.get(task_id)
            if info is None:
                continue

            info["status"] = "running"
            logger.info(f"Summary task {task_id} started")
            try:
                result = await self.summarize(messages=messages, **kwargs)
                info["status"] = "completed"
                info["result"] = result
                logger.info(f"Summary task {task_id} completed")
            except asyncio.CancelledError:
                info["status"] = "cancelled"
                logger.info(f"Summary task {task_id} cancelled")
                raise
            except BaseException as e:
                info["status"] = "failed"
                info["error"] = str(e)
                logger.error(f"Summary task {task_id} failed: {e}")

    def list_summarize_status(self) -> list[dict]:
        """Return status of all summary tasks as list of dicts.

        Each dict contains:
            - task_id: Unique identifier
            - start_time: When the task was enqueued
            - status: "pending", "running", "completed",
                "failed", or "cancelled"
            - result: Summary result (if completed)
            - error: Error message (if failed)

        Returns:
            List of task status dicts.
        """
        self._update_task_statuses()

        result = []
        for _task_id, info in self._summary_task_info.items():
            result.append(
                {
                    "task_id": info["task_id"],
                    "start_time": info["start_time"].isoformat(),
                    "status": info["status"],
                    "result": info["result"],
                    "error": info["error"],
                },
            )
        return result


# ---------------------------------------------------------------------------
# Registry and factory
# ---------------------------------------------------------------------------

memory_registry: Registry[BaseMemoryManager] = Registry()


def get_memory_manager_backend(backend: str) -> type[BaseMemoryManager]:
    """Return the memory manager class for the given backend name.

    If the backend is not registered, falls back to the first registered
    backend.

    Args:
        backend: Backend name to resolve.

    Returns:
        The memory manager class.

    Raises:
        ValueError: When no memory manager backends are registered.
    """
    cls = memory_registry.get(backend)
    if cls is None:
        registered = memory_registry.list_registered()
        if not registered:
            raise ValueError(
                f"No memory manager backends registered. "
                f"Requested: '{backend}'",
            )
        fallback = registered[0]
        logger.warning(
            f"Unsupported memory manager backend: '{backend}'. "
            f"Falling back to '{fallback}'. "
            f"Registered: {registered}",
        )
        cls = memory_registry.get(fallback)
        if cls is None:
            raise ValueError(
                f"Fallback backend '{fallback}' not found in registry. "
                f"This should not happen.",
            )
    return cls
