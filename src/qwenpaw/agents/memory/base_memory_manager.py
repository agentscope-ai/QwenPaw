# -*- coding: utf-8 -*-
"""Abstract base class for memory managers."""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional


from agentscope.formatter import FormatterBase
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.tool import ToolResponse

if TYPE_CHECKING:
    from reme.memory.file_based.reme_in_memory_memory import ReMeInMemoryMemory


logger = logging.getLogger(__name__)


class BaseMemoryManager(ABC):
    """Abstract base class defining the memory manager interface.

    All memory manager backends must implement this interface to be usable
    as a drop-in replacement within the workspace.

    Concrete implementations are responsible for managing conversation memory,
    including compaction, summarization, semantic search, and lifecycle
    management.

    Attributes:
        working_dir: Working directory path for memory storage.
        agent_id: Unique agent identifier.
        chat_model: Chat model used for compaction and summarization.
        formatter: Formatter paired with the chat model.
    """

    def __init__(
        self,
        working_dir: str,
        agent_id: str,
    ):
        """Initialize common memory manager attributes.

        Args:
            working_dir: Working directory path for memory storage.
            agent_id: Unique agent identifier.
        """
        self.working_dir: str = working_dir
        self.agent_id: str = agent_id
        self.chat_model: Optional[ChatModelBase] = None
        self.formatter: Optional[FormatterBase] = None

        # Initialize list to track background summarization tasks
        self.summary_tasks: list[asyncio.Task] = []
        # Initialize list to track background dream optimization tasks
        self.dream_tasks: list[asyncio.Task] = []

    @abstractmethod
    async def start(self) -> None:
        """Start the memory manager lifecycle."""

    @abstractmethod
    async def close(self) -> bool:
        """Close the memory manager and perform cleanup."""

    @abstractmethod
    async def compact_tool_result(self, **kwargs) -> None:
        """Compact tool results by truncating large outputs.

        Args:
            **kwargs: Compaction parameters (messages, thresholds, etc.).
        """

    @abstractmethod
    async def check_context(self, **kwargs) -> tuple:
        """Check context size and determine if compaction is needed.

        Args:
            **kwargs: Context check parameters (messages, thresholds, etc.).

        Returns:
            Tuple of (messages_to_compact, remaining_messages, is_valid).
        """

    @abstractmethod
    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
        **kwargs,
    ) -> str:
        """Compact a list of messages into a condensed summary.

        Args:
            messages: List of messages to compact.
            previous_summary: Optional previous summary to incorporate.
            extra_instruction: Optional manual instruction for compaction.
            **kwargs: Additional keyword arguments.

        Returns:
            Condensed summary string, or empty string on failure.
        """

    @abstractmethod
    async def summary_memory(self, messages: list[Msg], **kwargs) -> str:
        """Generate a comprehensive summary of the given messages.

        Args:
            messages: List of messages to summarize.
            **kwargs: Additional keyword arguments.

        Returns:
            Comprehensive summary string.
        """

    @abstractmethod
    async def dream_memory(self, **kwargs) -> None:
        """Run one dream-based memory optimization task.

        This method performs dream-based memory optimization by executing
        an agent query with specific instructions for memory file optimization.

        Args:
            **kwargs: Additional keyword arguments for the dream task.
        """

    def add_async_summary_task(self, messages: list[Msg], **kwargs):
        """Add an asynchronous summary task for the given messages."""

        remaining_tasks = []
        for task in self.summary_tasks:
            if task.done():
                if task.cancelled():
                    logger.warning("Summary task was cancelled.")
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.error(f"Summary task failed: {exc}")
                else:
                    result = task.result()
                    logger.info(f"Summary task completed: {result}")
            else:
                remaining_tasks.append(task)
        self.summary_tasks = remaining_tasks

        task = asyncio.create_task(
            self.summary_memory(messages=messages, **kwargs),
        )
        self.summary_tasks.append(task)

    async def await_summary_tasks(self) -> str:
        """
        Wait for all background summary tasks to complete and collect results.

        Blocks until all pending summary tasks in the task list have completed,
        canceled, or failed. Collects status information from each task and
        clears the task list after processing.

        Returns:
            str: A concatenated string of status messages, including:
                - Completion confirmations with results
                - Cancellation notices
                - Error messages for failed tasks

        Note:
            - This method will block if any tasks are still running
            - All tasks are removed from summary_tasks after this call
            - Task exceptions are logged but do not raise to the caller
            - Use this before application shutdown
        """
        result = ""
        for task in self.summary_tasks:
            if task.done():
                # Task has already completed, check its status
                if task.cancelled():
                    logger.warning("Summary task was cancelled.")
                    result += "Summary task was cancelled.\n"
                else:
                    # Check if the task raised an exception
                    exc = task.exception()
                    if exc is not None:
                        logger.error(f"Summary task failed: {exc}")
                        result += f"Summary task failed: {exc}\n"
                    else:
                        # Task completed successfully, collect result
                        task_result = task.result()
                        logger.info(f"Summary task completed: {task_result}")
                        result += f"Summary task completed: {task_result}\n"

            else:
                # Task is still running, wait for it to complete
                try:
                    task_result = await task
                    logger.info(f"Summary task completed: {task_result}")
                    result += f"Summary task completed: {task_result}\n"

                except asyncio.CancelledError:
                    logger.warning("Summary task was cancelled while waiting.")
                    result += "Summary task was cancelled.\n"

                except Exception as e:
                    logger.exception(f"Summary task failed: {e}")
                    result += f"Summary task failed: {e}\n"

        # Clear the task list after processing all tasks
        self.summary_tasks.clear()
        return result

    @abstractmethod
    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """Search stored memories for relevant content.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.
            min_score: Minimum relevance score threshold.

        Returns:
            ToolResponse containing search results.
        """

    @abstractmethod
    def get_in_memory_memory(self, **kwargs) -> "ReMeInMemoryMemory | None":
        """Retrieve the in-memory memory object for the agent.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            In-memory memory instance.
        """

    def add_async_dream_task(self, **kwargs):
        """Add an asynchronous dream optimization task.

        This method manages the dream_tasks list, cleaning up completed tasks
        and creating a new background task for dream-based memory optimization.
        """
        # Clean up completed dream tasks
        remaining_tasks = []
        for task in self.dream_tasks:
            if task.done():
                if task.cancelled():
                    logger.warning("Dream task was cancelled.")
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.error(f"Dream task failed: {exc}")
                else:
                    result = task.result()
                    logger.info(f"Dream task completed: {result}")
            else:
                remaining_tasks.append(task)
        self.dream_tasks = remaining_tasks

        # Create new dream task
        task = asyncio.create_task(
            self.dream_memory(**kwargs),
        )
        self.dream_tasks.append(task)

    async def await_dream_tasks(self) -> str:
        """
        Wait for all background dream tasks to complete and collect results.

        Blocks until all pending dream tasks in the task list have completed,
        canceled, or failed. Collects status information from each task and
        clears the task list after processing.

        Returns:
            str: A concatenated string of status messages, including:
                - Completion confirmations with results
                - Cancellation notices
                - Error messages for failed tasks
        """
        result = ""
        for task in self.dream_tasks:
            if task.done():
                # Task has already completed, check its status
                if task.cancelled():
                    logger.warning("Dream task was cancelled.")
                    result += "Dream task was cancelled.\n"
                else:
                    # Check if the task raised an exception
                    exc = task.exception()
                    if exc is not None:
                        logger.error(f"Dream task failed: {exc}")
                        result += f"Dream task failed: {exc}\n"
                    else:
                        # Task completed successfully, collect result
                        task_result = task.result()
                        logger.info(f"Dream task completed: {task_result}")
                        result += f"Dream task completed: {task_result}\n"

            else:
                # Task is still running, wait for it to complete
                try:
                    task_result = await task
                    logger.info(f"Dream task completed: {task_result}")
                    result += f"Dream task completed: {task_result}\n"

                except asyncio.CancelledError:
                    logger.warning("Dream task was cancelled while waiting.")
                    result += "Dream task was cancelled.\n"

                except Exception as e:
                    logger.exception(f"Dream task failed: {e}")
                    result += f"Dream task failed: {e}\n"

        # Clear the task list after processing all tasks
        self.dream_tasks.clear()
        return result
