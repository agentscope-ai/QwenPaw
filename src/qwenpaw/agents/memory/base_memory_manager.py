# -*- coding: utf-8 -*-
"""Abstract base class for memory managers."""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agentscope.message import AssistantMsg, Msg, TextBlock, ThinkingBlock
from agentscope.message import ToolCallBlock, ToolCallState
from agentscope.message import ToolResultBlock, ToolResultState
from agentscope.message import Usage
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolChunk

from ...constant import (
    AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY,
    AUTO_MEMORY_SEARCH_TEXT,
    AUTO_MEMORY_SEARCH_THINKING_PREFIX,
)
from ...app.crons.contracts import ServiceCronJob
from ..utils.registry import Registry

logger = logging.getLogger(__name__)
MAX_QUERY_CHARS = 50
AUTO_MEMORY_WORKER_CLOSE_TIMEOUT_SECONDS = 5.0
MAX_AUTO_MEMORY_TASK_HISTORY = 100
MAX_RUNTIME_TASK_HISTORY = 20
MAX_RUNTIME_RESULT_CHARS = 4000
MAX_RUNTIME_ERROR_CHARS = 240
AUTO_MEMORY_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
NO_RELEVANT_MEMORIES = "No relevant memories found."


@dataclass(frozen=True)
class AutoMemorySearchOptions:
    """Backend-independent settings for automatic memory recall."""

    max_results: int = 3
    estimate_divisor: float = 4.0
    max_context_bytes: int | None = None


class BaseMemoryManager(ABC):
    """Abstract base class for memory manager backends.

    Lifecycle:
        1. Instantiate with ``working_dir`` and ``agent_id``.
        2. ``await start()`` – initialize storage backend.
        3. Use ``auto_memory()``, ``memory_search()``, etc. during session.
        4. ``await close()`` – flush and release resources.

    Attributes:
        working_dir: Root directory for persisting memory files.
        agent_id: Unique identifier of the owning agent.
    """

    enabled = True

    def __init__(self, working_dir: str, agent_id: str):
        self.working_dir: str = working_dir
        self.agent_id: str = agent_id
        self._auto_memory_task_info: dict[str, dict[str, Any]] = {}
        self._task_counter: int = 0
        self._auto_memory_task_queue: asyncio.Queue[
            tuple[str, list[Msg], dict]
        ] = asyncio.Queue()
        self._auto_memory_worker_task: asyncio.Task | None = None
        self._auto_memory_worker_stopping = False

    @abstractmethod
    async def start(self) -> None:
        """Initialize the storage backend. Called once after instantiation."""

    async def close(self) -> bool:
        """Stop shared workers, then release backend-specific resources.

        Returns:
            ``True`` if shutdown completed cleanly.
        """
        if not await self._shutdown_auto_memory_worker():
            return False
        return await self._close_backend()

    async def _close_backend(self) -> bool:
        """Release backend-specific resources after shared workers stop."""
        return True

    def get_memory_prompt(self) -> str:
        """Return the memory guidance prompt for inclusion
        in the system prompt.

        Returns:
            Formatted memory guidance string.
        """
        return ""

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        """Return the standard memory-search tool when it is enabled."""
        return [self.memory_search] if self.is_memory_search_enabled() else []

    def is_memory_search_enabled(self) -> bool:
        """Return whether ``memory_search`` is exposed to the agent."""
        return True

    @abstractmethod
    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> ToolChunk:
        """Search long-term memory and return a tool-compatible result."""

    def build_middlewares(self) -> list[MiddlewareBase]:
        """Return AgentScope middlewares contributed by this manager.

        Tool registration remains a toolkit construction concern.  This hook
        is only for prompt/model-call/reply lifecycle behavior.
        """
        from ..middlewares import MemoryMiddleware

        return [MemoryMiddleware(memory_manager=self)]

    def list_cron_jobs(self) -> list[ServiceCronJob]:
        """Return background jobs contributed by this memory backend.

        Cron jobs are an optional backend capability. The cron manager owns
        their scheduling lifecycle and does not need to understand their
        domain-specific purpose or configuration.
        """
        return []

    def get_auto_memory_interval(self) -> int:
        """Return the lifecycle auto-memory interval for this backend.

        ``0`` disables middleware-driven periodic auto-memory. Backends that
        support automatic persistence should override this with their own
        configuration or fixed cadence.
        """
        return 0

    def _build_auto_memory_search_msg(
        self,
        *,
        query: str,
        max_results: int,
        text: str,
        estimate_divisor: float = 4.0,
    ) -> Msg:
        """Build the simulated assistant tool interaction for memory search."""
        tool_call_id = uuid.uuid4().hex
        tool_input = {
            "query": query,
            "max_results": max_results,
        }
        thinking_text = (
            f"{AUTO_MEMORY_SEARCH_THINKING_PREFIX} I will use the "
            f"memory_search with the user's query as the search keywords, "
            f"request up to {max_results} result"
            f"{'' if max_results == 1 else 's'}."
        )
        text_block = TextBlock(text=AUTO_MEMORY_SEARCH_TEXT)
        thinking_block = ThinkingBlock(thinking=thinking_text)
        tool_call_block = ToolCallBlock(
            id=tool_call_id,
            name="memory_search",
            input=json.dumps(tool_input, ensure_ascii=False),
            state=ToolCallState.FINISHED,
        )
        tool_result_block = ToolResultBlock(
            id=tool_call_id,
            name="memory_search",
            output=[TextBlock(text=text)],
            state=ToolResultState.SUCCESS,
        )
        estimated_input_tokens = sum(
            self._estimate_message_text_tokens(part, estimate_divisor)
            for part in (
                AUTO_MEMORY_SEARCH_TEXT,
                thinking_text,
                tool_call_block.name + tool_call_block.input,
                tool_result_block.name + text,
            )
        )
        # Keep a synthetic sender to avoid merging into the real agent reply.
        return AssistantMsg(
            name="memory_search",
            metadata={
                AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY: [
                    text_block.id,
                    thinking_block.id,
                    tool_call_block.id,
                    tool_result_block.id,
                ],
                "auto_memory_search_usage": {
                    "estimated": True,
                    "input_tokens": estimated_input_tokens,
                    "output_tokens": 0,
                    "estimate_divisor": estimate_divisor,
                },
            },
            content=[
                text_block,
                thinking_block,
                tool_call_block,
                tool_result_block,
            ],
            usage=Usage(
                input_tokens=estimated_input_tokens,
                output_tokens=0,
            ),
        )

    def _get_token_estimate_divisor(self) -> float:
        """Return configured byte/token divisor for lightweight estimates."""
        try:
            from ...config.config import load_agent_config

            agent_config = load_agent_config(self.agent_id)
            return self._resolve_token_estimate_divisor(agent_config)
        except Exception:
            logger.debug(
                "Failed to load token_count_estimate_divisor for %s",
                self.agent_id,
                exc_info=True,
            )
        return 4

    @staticmethod
    def _resolve_token_estimate_divisor(agent_config: Any) -> float:
        """Resolve a positive token estimate divisor from agent config."""
        try:
            light_context_config = agent_config.running.light_context_config
            divisor = float(light_context_config.token_count_estimate_divisor)
            if divisor > 0:
                return divisor
        except (AttributeError, TypeError, ValueError):
            pass
        return 4

    @staticmethod
    def _estimate_message_text_tokens(
        text: str,
        estimate_divisor: float,
    ) -> int:
        """Estimate context tokens using the shared byte-length heuristic."""
        if not text:
            return 0
        return int(len(text.encode("utf-8")) / estimate_divisor + 0.5)

    @abstractmethod
    async def auto_memory(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Extract and persist memory for one prepared message batch."""

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs,
    ) -> dict | None:
        """Auto-search memory before replying using the common recall flow.

        Args:
            messages: The incoming user message(s).
            agent_name: Name of the owning agent.

        Returns:
            None if auto-search is disabled or no relevant memory found.
            dict with updated kwargs if memory context should be merged.
        """
        del agent_name, kwargs
        options = await self.get_auto_memory_search_options()
        if options is None:
            return None

        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None

        max_results = max(1, int(options.max_results))
        result = await self._search_for_auto_memory(
            query=query,
            options=options,
        )
        if result.state != ToolResultState.SUCCESS:
            return None
        text = self._tool_chunk_text(result).strip()
        if self._is_empty_memory_search_result(text):
            return None

        assistant_msg = self._build_auto_memory_search_msg(
            query=query,
            max_results=max_results,
            text=text,
            estimate_divisor=options.estimate_divisor,
        )
        return {
            "query": query,
            "text": text,
            "msg": msgs + [assistant_msg],
        }

    async def get_auto_memory_search_options(
        self,
    ) -> AutoMemorySearchOptions | None:
        """Return auto-search settings, or ``None`` when it is disabled."""
        return None

    async def _search_for_auto_memory(
        self,
        *,
        query: str,
        options: AutoMemorySearchOptions,
    ) -> ToolChunk:
        """Run the backend search used by automatic recall."""
        return await self.memory_search(
            query=query,
            max_results=max(1, int(options.max_results)),
        )

    @staticmethod
    def _tool_chunk_text(chunk: ToolChunk) -> str:
        """Extract all textual content from a tool result."""
        return "\n".join(
            str(getattr(block, "text", ""))
            for block in chunk.content or []
            if getattr(block, "text", "")
        )

    @staticmethod
    def _is_empty_memory_search_result(text: str) -> bool:
        """Return whether a successful search contains no usable recall."""
        return not text or text in {
            NO_RELEVANT_MEMORIES,
            "(no memory results)",
        }

    @staticmethod
    def _build_query(messages: list[Msg]) -> str:
        for msg in reversed(messages):
            if msg.role != "user":
                continue
            text = (msg.get_text_content() or "").strip()
            if text:
                return text[:MAX_QUERY_CHARS]
        return ""

    @classmethod
    def _messages_without_auto_memory_search(
        cls,
        messages: list[Msg],
    ) -> list[Msg]:
        sanitized_messages: list[Msg] = []
        for msg in messages:
            sanitized = cls._message_without_auto_memory_search(msg)
            if sanitized is not None:
                sanitized_messages.append(sanitized)
        return sanitized_messages

    @classmethod
    def message_without_auto_memory_search(cls, msg: Msg) -> Msg | None:
        """Return ``msg`` with synthetic auto-memory-search blocks removed."""
        return cls._message_without_auto_memory_search(msg)

    @staticmethod
    def _auto_memory_search_block_ids(msg: Msg) -> set[str]:
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            return set()
        return set(metadata.get(AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY) or [])

    @classmethod
    def _message_without_auto_memory_search(cls, msg: Msg) -> Msg | None:
        block_ids = cls._auto_memory_search_block_ids(msg)
        if not block_ids:
            return msg

        kept_blocks = [
            block
            for block in msg.get_content_blocks()
            if getattr(block, "id", "") not in block_ids
        ]
        if not kept_blocks:
            return None

        sanitized = deepcopy(msg)
        sanitized.content = kept_blocks
        if isinstance(sanitized.metadata, dict):
            sanitized.metadata.pop(AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY, None)
        return sanitized

    async def _auto_memory_worker(self) -> None:
        """Process queued auto-memory tasks serially."""
        while True:
            (
                task_id,
                messages,
                kwargs,
            ) = await self._auto_memory_task_queue.get()
            try:
                info = self._auto_memory_task_info.get(task_id)
                if info is None:
                    continue

                info["status"] = "running"
                logger.info("Auto-memory task %s started", task_id)
                try:
                    result = await self.auto_memory(
                        messages=messages,
                        **kwargs,
                    )
                    info["status"] = "completed"
                    info["result"] = result
                    logger.info("Auto-memory task %s completed", task_id)
                except asyncio.CancelledError:
                    info["status"] = "cancelled"
                    logger.info("Auto-memory task %s cancelled", task_id)
                    raise
                except Exception as e:
                    info["status"] = "failed"
                    info["error"] = str(e)
                    logger.error("Auto-memory task %s failed: %s", task_id, e)
                finally:
                    info["finished_at"] = datetime.now(timezone.utc)
                    self._prune_auto_memory_task_info()
            finally:
                self._auto_memory_task_queue.task_done()

            if (
                self._auto_memory_worker_stopping
                and self._auto_memory_task_queue.empty()
            ):
                return

    async def _shutdown_auto_memory_worker(
        self,
        timeout: float = AUTO_MEMORY_WORKER_CLOSE_TIMEOUT_SECONDS,
    ) -> bool:
        """Stop the auto-memory worker without allowing shutdown to hang.

        The stopping flag is required in addition to ``Task.cancel()``:
        cancellation may be consumed by a nested model/job call. In that
        case the worker exits after the current auto-memory call returns rather
        than looping back to an empty queue forever.
        """
        self._auto_memory_worker_stopping = True
        worker = self._auto_memory_worker_task
        if worker is None:
            return True

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        queue_drained = asyncio.create_task(
            self._auto_memory_task_queue.join(),
        )
        done, _pending = await asyncio.wait(
            {queue_drained},
            timeout=max(0.0, deadline - loop.time()),
        )
        if not done:
            queue_drained.cancel()
            await asyncio.gather(queue_drained, return_exceptions=True)
            logger.warning(
                "Auto-memory queue did not drain within %.1fs; "
                "cancelling remaining work: agent_id=%s",
                timeout,
                self.agent_id,
            )

        if not worker.done():
            worker.cancel()
            # Give cancellation an event-loop turn even when draining used the
            # complete timeout budget.
            await asyncio.sleep(0)
            done, _pending = await asyncio.wait(
                {worker},
                timeout=max(0.0, deadline - loop.time()),
            )
            if not done:
                # A second cancellation handles the common case where the
                # first one was swallowed and the worker has since reached
                # another cancellation point. Do not await it without a
                # bound: a coroutine is allowed to suppress cancellation.
                worker.cancel()
                logger.error(
                    "Auto-memory worker did not stop within %.1fs: "
                    "agent_id=%s",
                    timeout,
                    self.agent_id,
                )
                return False

        while not self._auto_memory_task_queue.empty():
            try:
                (
                    task_id,
                    _messages,
                    _kwargs,
                ) = self._auto_memory_task_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            info = self._auto_memory_task_info.get(task_id)
            if info is not None and info.get("status") == "pending":
                info["status"] = "cancelled"
                info["finished_at"] = datetime.now(timezone.utc)
            self._auto_memory_task_queue.task_done()

        self._auto_memory_worker_task = None
        self._prune_auto_memory_task_info()
        return True

    def submit_auto_memory(
        self,
        messages: list[Msg],
        *,
        trigger: str = "manual",
        **kwargs: Any,
    ) -> str:
        """Submit an auto-memory task without blocking and return its ID.

        Tasks are executed serially in FIFO order. If no task is running,
        execution starts immediately; otherwise the task queues.

        Args:
            messages: Messages to pass to ``auto_memory()``.
            **kwargs: Forwarded to ``auto_memory()``.
        """
        if self._auto_memory_worker_stopping:
            raise RuntimeError("Auto-memory worker is shutting down")

        # Ensure worker is running
        if (
            self._auto_memory_worker_task is None
            or self._auto_memory_worker_task.done()
        ):
            self._auto_memory_worker_task = asyncio.create_task(
                self._auto_memory_worker(),
            )

        self._task_counter += 1
        task_id = f"task_{self._task_counter}"

        self._auto_memory_task_info[task_id] = {
            "task_id": task_id,
            "start_time": datetime.now(timezone.utc),
            "status": "pending",
            "message_count": len(messages),
            "trigger": trigger,
            "result": None,
            "error": None,
            "finished_at": None,
        }

        # Enqueue for serial execution
        self._auto_memory_task_queue.put_nowait((task_id, messages, kwargs))
        return task_id

    def _prune_auto_memory_task_info(self) -> None:
        """Keep active tasks and only the latest terminal task history."""
        terminal_ids = [
            task_id
            for task_id, info in self._auto_memory_task_info.items()
            if info["status"] in AUTO_MEMORY_TERMINAL_STATUSES
        ]
        for task_id in terminal_ids[:-MAX_AUTO_MEMORY_TASK_HISTORY]:
            self._auto_memory_task_info.pop(task_id, None)

    def _update_task_statuses(self) -> None:
        """Update status for pending/running tasks if worker was cancelled."""
        if self._auto_memory_worker_task is None:
            return
        if not self._auto_memory_worker_task.done():
            return

        # Worker finished - update any running tasks
        for task_id, info in self._auto_memory_task_info.items():
            if info["status"] == "running":
                if self._auto_memory_worker_task.cancelled():
                    info["status"] = "cancelled"
                    info["finished_at"] = datetime.now(timezone.utc)
                    logger.info(
                        "Auto-memory task %s cancelled (worker stopped)",
                        task_id,
                    )
                else:
                    exc = self._auto_memory_worker_task.exception()
                    if exc is not None:
                        info["status"] = "failed"
                        info["error"] = str(exc)
                        info["finished_at"] = datetime.now(timezone.utc)
                        logger.error(
                            "Auto-memory task %s failed: %s",
                            task_id,
                            exc,
                        )
        self._prune_auto_memory_task_info()

    def list_auto_memory_tasks(self) -> list[dict]:
        """Return the status of all queued auto-memory tasks.

        Each dict contains:
            - task_id: Unique identifier
            - start_time: When the task was enqueued
            - trigger: Why the task was submitted
            - status: "pending", "running", "completed",
                "failed", or "cancelled"
            - result: Auto-memory result (if completed)
            - error: Error message (if failed)

        Returns:
            List of task status dicts.
        """
        self._update_task_statuses()

        result = []
        for _task_id, info in self._auto_memory_task_info.items():
            result.append(
                {
                    "task_id": info["task_id"],
                    "start_time": info["start_time"].isoformat(),
                    "status": info["status"],
                    "trigger": info.get("trigger", "manual"),
                    "result": info["result"],
                    "error": info["error"],
                },
            )
        return result

    def get_runtime_status(
        self,
        *,
        auto_memory_interval: int | None = None,
    ) -> dict[str, Any]:
        """Return a sanitized operational snapshot for status UIs.

        Auto-memory history includes the same bounded result text used for
        inbox notifications. The shared auto-memory queue contains periodic
        auto-memory work as well as user-triggered ``/new`` and ``/compact``
        work, so callers must preserve each task's trigger context.
        It deliberately excludes messages, session identifiers, and task
        kwargs.
        """
        self._update_task_statuses()

        task_infos = list(self._auto_memory_task_info.values())
        pending_tasks = sum(
            info.get("status") == "pending" for info in task_infos
        )
        running_tasks = sum(
            info.get("status") == "running" for info in task_infos
        )

        worker = self._auto_memory_worker_task
        if self._auto_memory_worker_stopping:
            worker_status = "stopping"
        elif running_tasks:
            worker_status = "busy"
        elif worker is None:
            worker_status = "error" if pending_tasks else "idle"
        elif not worker.done():
            worker_status = "idle"
        elif worker.cancelled():
            worker_status = "error" if pending_tasks else "idle"
        else:
            worker_status = (
                "error"
                if worker.exception() is not None or pending_tasks
                else "idle"
            )

        last_failed = next(
            (
                info
                for info in reversed(task_infos)
                if info.get("status") == "failed"
            ),
            None,
        )

        interval = max(
            0,
            int(
                (
                    self.get_auto_memory_interval()
                    if auto_memory_interval is None
                    else auto_memory_interval
                ),
            ),
        )

        def _iso_time(info: dict[str, Any] | None, key: str) -> str | None:
            if info is None:
                return None
            value = info.get(key)
            return value.isoformat() if isinstance(value, datetime) else None

        def _bounded_text(
            value: Any,
            limit: int,
            *,
            single_line: bool = False,
        ) -> str | None:
            text = str(value or "").strip()
            if not text:
                return None
            if single_line:
                text = " ".join(text.split())
            return text[:limit]

        tasks = []
        for info in reversed(task_infos[-MAX_RUNTIME_TASK_HISTORY:]):
            tasks.append(
                {
                    "task_id": str(info.get("task_id") or ""),
                    "status": str(info.get("status") or "pending"),
                    "queued_at": _iso_time(info, "start_time"),
                    "finished_at": _iso_time(info, "finished_at"),
                    "message_count": max(
                        0,
                        int(info.get("message_count") or 0),
                    ),
                    "trigger": str(info.get("trigger") or "manual"),
                    "result": _bounded_text(
                        info.get("result"),
                        MAX_RUNTIME_RESULT_CHARS,
                    ),
                    "error": _bounded_text(
                        info.get("error"),
                        MAX_RUNTIME_ERROR_CHARS,
                    ),
                },
            )

        return {
            "worker": {
                "status": worker_status,
                "queue_pending": self._auto_memory_task_queue.qsize(),
                "tasks_running": running_tasks,
            },
            "auto_memory": {
                "enabled": interval > 0,
                "interval": interval,
            },
            "tasks": tasks,
            "recent": {
                "last_error": _bounded_text(
                    last_failed.get("error") if last_failed else None,
                    MAX_RUNTIME_ERROR_CHARS,
                    single_line=True,
                ),
            },
            "reindexing": bool(getattr(self, "is_reindexing", False)),
        }


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
