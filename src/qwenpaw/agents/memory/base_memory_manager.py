# -*- coding: utf-8 -*-
"""Abstract base class for memory managers."""
import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
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
from ..utils.registry import Registry

logger = logging.getLogger(__name__)
AUTO_MEMORY_TURN_STATE_TTL_SECONDS = 24 * 60 * 60
MAX_QUERY_CHARS = 50
SUMMARY_WORKER_CLOSE_TIMEOUT_SECONDS = 5.0
MAX_SUMMARY_TASK_HISTORY = 100
SUMMARY_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


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
        self._auto_memory_turn_states: dict[str, dict[str, Any]] = {}
        self._task_counter: int = 0
        self._task_queue: asyncio.Queue[
            tuple[str, list[Msg], dict]
        ] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._worker_stopping = False

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
    def get_memory_prompt(self) -> str:
        """Return the memory guidance prompt for inclusion
        in the system prompt.

        Returns:
            Formatted memory guidance string.
        """

    @abstractmethod
    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        """Return tool functions exposed to the agent for memory access.

        Each returned callable may have any signature but must return a
        ``ToolChunk``.  Implementations register whatever memory-related
        tools make sense for the backend (e.g. semantic search, listing).

        Returns:
            Ordered list of tool functions to register with the agent toolkit.
        """

    def build_middlewares(self) -> list[MiddlewareBase]:
        """Return AgentScope middlewares contributed by this manager.

        Tool registration remains a toolkit construction concern.  This hook
        is only for prompt/model-call/reply lifecycle behavior.
        """
        from ..middlewares import MemoryMiddleware

        return [MemoryMiddleware(memory_manager=self)]

    def get_memory_config(self) -> Any:
        """Return backend-specific memory configuration.

        The shared memory middleware uses this hook for optional lifecycle
        controls without depending on a concrete backend's config path.
        """
        return None

    def get_auto_memory_interval(self) -> int:
        """Return the lifecycle auto-memory interval for this backend.

        ``0`` disables middleware-driven periodic auto-memory. Backends that
        support automatic persistence should override this with their own
        configuration or fixed cadence.
        """
        return 0

    def get_auto_memory_turn_state(self, session_id: str) -> dict[str, Any]:
        """Return persistent auto-memory turn tracking state for a session."""
        now = time.monotonic()
        expired_before = now - AUTO_MEMORY_TURN_STATE_TTL_SECONDS
        for state_key, state in list(self._auto_memory_turn_states.items()):
            touched_at = float(state.get("touched_at") or 0)
            if touched_at < expired_before:
                self._auto_memory_turn_states.pop(state_key, None)

        key = session_id or "__default__"
        state = self._auto_memory_turn_states.setdefault(
            key,
            {
                "pending": [],
                "seen": {},
                "touched_at": now,
            },
        )
        state["touched_at"] = now
        return state

    def _build_auto_memory_search_msg(
        self,
        *,
        query: str,
        max_results: int,
        text: str,
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
        estimate_divisor = self._get_token_estimate_divisor()
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
            lcc = agent_config.running.light_context_config
            divisor = lcc.token_count_estimate_divisor
            divisor = float(divisor)
            if divisor > 0:
                return divisor
        except Exception:
            logger.debug(
                "Failed to load token_count_estimate_divisor for %s",
                self.agent_id,
                exc_info=True,
            )
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
    async def dream(self, **kwargs) -> None:
        """Optimize memory files via a background agent pass.

        NOTE: This method is optional. Subclasses may override this method
        to implement actual memory optimization. Base implementation does
        nothing, indicating no dream support.

        Runs a lightweight ReAct agent with file-editing tools to
        consolidate redundant or outdated memory entries.
        """
        return None

    async def reme_status(self) -> Any | None:
        """Return ReMe runtime status when supported by the backend."""
        return None

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs,
    ) -> dict | None:
        """Auto-search memory before replying (pre_reply phase).

        Implementations should check internal config to decide whether
        auto search is enabled, and if so, retrieve relevant memory context.

        Args:
            messages: The incoming user message(s).
            agent_name: Name of the owning agent.

        Returns:
            None if auto-search is disabled or no relevant memory found.
            dict with updated kwargs if memory context should be merged.
        """
        return None

    @staticmethod
    def _build_query(messages: list[Msg]) -> str:
        for msg in reversed(messages):
            if msg.role != "user":
                continue
            text = (msg.get_text_content() or "").strip()
            if text:
                return text[:MAX_QUERY_CHARS]
        return ""

    async def auto_memory(
        self,
        all_messages: list[Msg],
        **kwargs,
    ) -> None:
        """Periodically auto-extract memory from conversation.

        Called during post_reply. Implementations should check internal
        config (e.g. auto_memory_interval) and trigger memory extraction
        at the configured cadence.

        Args:
            all_messages: All conversation messages.
        """
        return None

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

    async def _summarize_worker(self) -> None:
        """Background worker that processes summarize tasks serially."""
        while not self._worker_stopping:
            task_id, messages, kwargs = await self._task_queue.get()
            if self._worker_stopping:
                return
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
            finally:
                self._prune_summary_task_info()

    async def _shutdown_summarize_worker(
        self,
        timeout: float = SUMMARY_WORKER_CLOSE_TIMEOUT_SECONDS,
    ) -> bool:
        """Stop the summary worker without allowing shutdown to hang.

        The stopping flag is required in addition to ``Task.cancel()``:
        cancellation may be consumed by a nested model/job call. In that
        case the worker exits after the current summarize call returns rather
        than looping back to an empty queue forever.
        """
        self._worker_stopping = True
        worker = self._worker_task
        if worker is None:
            return True

        if not worker.done():
            worker.cancel()
            done, _pending = await asyncio.wait({worker}, timeout=timeout)
            if not done:
                # A second cancellation handles the common case where the
                # first one was swallowed and the worker has since reached
                # another cancellation point. Do not await it without a
                # bound: a coroutine is allowed to suppress cancellation.
                worker.cancel()
                logger.error(
                    "Summary worker did not stop within %.1fs: agent_id=%s",
                    timeout,
                    self.agent_id,
                )
                return False

        self._worker_task = None
        return True

    def add_summarize_task(self, messages: list[Msg], **kwargs):
        """Schedule a background summarization task without blocking.

        Tasks are executed serially in FIFO order. If no task is running,
        execution starts immediately; otherwise the task queues.

        Args:
            messages: Messages to pass to ``summarize()``.
            **kwargs: Forwarded to ``summarize()``.
        """
        # Ensure worker is running
        self._worker_stopping = False
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._summarize_worker())

        self._task_counter += 1
        task_id = f"task_{self._task_counter}"

        self._summary_task_info[task_id] = {
            "task_id": task_id,
            "start_time": datetime.now(),
            "status": "pending",
            "result": None,
            "error": None,
        }

        # Enqueue for serial execution
        self._task_queue.put_nowait((task_id, messages, kwargs))

    def _prune_summary_task_info(self) -> None:
        """Keep active tasks and only the latest terminal task history."""
        terminal_ids = [
            task_id
            for task_id, info in self._summary_task_info.items()
            if info["status"] in SUMMARY_TERMINAL_STATUSES
        ]
        for task_id in terminal_ids[:-MAX_SUMMARY_TASK_HISTORY]:
            self._summary_task_info.pop(task_id, None)

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
        self._prune_summary_task_info()

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
