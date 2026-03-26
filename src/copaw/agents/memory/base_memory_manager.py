# -*- coding: utf-8 -*-
"""Abstract base class for CoPaw memory managers."""
from abc import ABC, abstractmethod
from typing import Optional

from agentscope.formatter import FormatterBase
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.tool import ToolResponse


class BaseMemoryManager(ABC):
    """Abstract base class defining the memory manager interface.

    All memory manager backends must implement this interface to be usable
    as a drop-in replacement within the CoPaw workspace.

    Concrete implementations are responsible for managing conversation memory,
    including compaction, summarization, semantic search, and lifecycle
    management.

    Attributes:
        agent_id: Unique agent identifier.
        chat_model: Chat model used for compaction and summarization.
        formatter: Formatter paired with the chat model.
    """

    agent_id: str
    chat_model: Optional[ChatModelBase]
    formatter: Optional[FormatterBase]

    @abstractmethod
    async def start(self) -> None:
        """Start the memory manager lifecycle."""

    @abstractmethod
    async def close(self) -> bool:
        """Close the memory manager and perform cleanup.

        Returns:
            True if closed successfully, False otherwise.
        """

    @abstractmethod
    def prepare_model_formatter(self) -> None:
        """Prepare and initialize the chat model and formatter.

        Called before operations that require model access.
        """

    @abstractmethod
    async def restart_embedding_model(self) -> None:
        """Restart the embedding model with the current configuration."""

    @abstractmethod
    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        **kwargs,
    ) -> str:
        """Compact a list of messages into a condensed summary.

        Args:
            messages: List of messages to compact.
            previous_summary: Optional previous summary to incorporate.
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
    def get_in_memory_memory(self, **kwargs):
        """Retrieve the in-memory memory object for the agent.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            In-memory memory instance.
        """

    @abstractmethod
    async def compact_tool_result(self, **kwargs):
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
    def add_async_summary_task(self, **kwargs):
        """Schedule an asynchronous background summary task.

        Args:
            **kwargs: Task parameters (e.g., messages to summarize).
        """
