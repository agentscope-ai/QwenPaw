# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Memory Manager for CoPaw agents.

Inherits from ReMeCopaw to provide memory management capabilities including:
- Message compaction and summarization
- Semantic memory search
- Memory file retrieval
- Tool result compaction
"""
import logging

from agentscope.formatter import FormatterBase
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.token import HuggingFaceTokenCounter
from agentscope.tool import Toolkit

from ...config.utils import load_config
from ...constant import MEMORY_COMPACT_RATIO

logger = logging.getLogger(__name__)

# Try to import reme, log warning if it fails
try:
    from reme.reme_copaw import ReMeCopaw

    _REME_AVAILABLE = True

except ImportError:
    _REME_AVAILABLE = False
    logger.warning("reme package not installed.")

    class ReMeCopaw:  # type: ignore
        """Placeholder when reme is not available."""


class MemoryManager(ReMeCopaw):
    """Memory manager that extends ReMeCopaw functionality for CoPaw agents.

    This class provides memory management capabilities including:
    - Memory compaction for long conversations
    - Semantic memory search using vector and full-text search
    - Memory file retrieval with pagination
    - Tool result compaction with file-based storage
    """

    def __init__(
        self,
        working_dir: str,
        chat_model: ChatModelBase,
        formatter: FormatterBase,
        token_counter: HuggingFaceTokenCounter,
        toolkit: Toolkit,
        max_input_length: int,
        memory_compact_ratio: float,
        vector_weight: float = 0.7,
        candidate_multiplier: float = 3.0,
        tool_result_threshold: int = 1000,
        retention_days: int = 7,
    ):
        """Initialize MemoryManager with ReMeCopaw configuration.

        Args:
            working_dir: Working directory path for memory storage
            chat_model: Language model for generating summaries
            formatter: Formatter for structuring model inputs/outputs
            token_counter: Token counting utility for length management
            toolkit: Collection of tools available to the application
            max_input_length: Maximum allowed input length in tokens
            memory_compact_ratio: Ratio at which to trigger compaction
                (0.0-1.0)
            vector_weight: Weight for vector search in hybrid search (0.0-1.0)
            candidate_multiplier: Multiplier for candidate retrieval in search
            tool_result_threshold: Size threshold for tool result compaction
            retention_days: Number of days to retain tool result files
        """
        if not _REME_AVAILABLE:
            raise RuntimeError("reme package not installed.")

        # Get language from config if not provided
        global_config = load_config()
        config_language = global_config.agents.language
        language = "zh" if config_language == "zh" else ""

        # Initialize parent ReMeCopaw class
        super().__init__(
            working_dir=working_dir,
            chat_model=chat_model,
            formatter=formatter,
            token_counter=token_counter,
            toolkit=toolkit,
            max_input_length=max_input_length,
            memory_compact_ratio=memory_compact_ratio,
            language=language,
            vector_weight=vector_weight,
            candidate_multiplier=candidate_multiplier,
            tool_result_threshold=tool_result_threshold,
            retention_days=retention_days,
        )

    def update_config_params(self):
        global_config = load_config()
        config_language = global_config.agents.language
        max_input_length = global_config.agents.running.max_input_length
        super().update_params(
            max_input_length=max_input_length,
            memory_compact_ratio=MEMORY_COMPACT_RATIO,
            language=config_language,
        )

    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
    ) -> str:
        """
        Compact a list of messages into a condensed summary.

        This method uses the Compactor to reduce the length of message history
        while preserving essential information. It's useful when conversation
        history approaches the maximum input length limit.

        Args:
            messages (list[Msg]): The list of messages to compact
            previous_summary (str): Optional previous summary to incorporate
                into the compaction process for continuity

        Returns:
            str: A compacted summary of messages, or empty string on failure

        Note:
            - Compaction uses the configured language model to generate
              summaries
            - The compaction threshold determines when compaction is triggered
            - If compaction fails, an empty string is returned
        """
        self.update_config_params()
        return await super().compact_memory(
            messages=messages,
            previous_summary=previous_summary,
        )

    async def summary_memory(self, messages: list[Msg]) -> str:
        """
        Generate a comprehensive summary of the given messages.

        This method uses the Summarizer to create a detailed summary of the
        conversation history, which can be stored as persistent memory. Unlike
        compaction, summarization aims to capture key information in a format
        suitable for long-term storage and retrieval.

        Args:
            messages (list[Msg]): The list of messages to summarize

        Returns:
            str: A generated summary of the messages, or empty string
                on failure

        Note:
            - Summarization may use tools from the toolkit to enhance
              the summary
            - The summary is typically stored in the memory directory
            - If summarization fails, an empty string is returned
        """
        self.update_config_params()
        return await super().summary_memory(messages)
