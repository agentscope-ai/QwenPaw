# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Memory Manager for CoPaw agents.

Extends ReMeLight to provide memory management capabilities including:
- Message compaction with configurable ratio
- Memory summarization with tool support
- Vector and full-text search integration
- Embedding configuration from environment variables
"""

import asyncio
import logging
import os
import platform
from typing import TYPE_CHECKING

from agentscope.formatter import FormatterBase
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.tool import Toolkit, ToolResponse
from copaw.agents.model_factory import create_model_and_formatter
from copaw.agents.tools import read_file, write_file, edit_file
from copaw.agents.utils import _get_copaw_token_counter
from copaw.agents.memory.embedding_adapter import create_embedding_adapter

if TYPE_CHECKING:
    from copaw.agents.memory.embedding_adapter import EmbeddingAdapter
    from copaw.config.config import AgentProfileConfig

logger = logging.getLogger(__name__)

# Try to import reme, log warning if it fails
try:
    from reme.reme_light import ReMeLight

    _REME_AVAILABLE = True

except ImportError as e:
    _REME_AVAILABLE = False
    logger.warning("reme package not installed. %s", e)

    class ReMeLight:  # type: ignore
        """Placeholder when reme is not available."""

        async def start(self) -> None:
            """No-op start when reme is unavailable."""


class MemoryManager(ReMeLight):
    """Memory manager that extends ReMeLight for CoPaw agents.

    This class provides memory management capabilities including:
    - Memory compaction for long conversations via compact_memory()
    - Memory summarization with file operation tools via summary_memory()
    - In-memory memory retrieval via get_in_memory_memory()
    - Configurable vector search and full-text search backends
    """

    def __init__(
        self,
        working_dir: str,
        agent_config: "AgentProfileConfig",
    ):
        """Initialize MemoryManager with ReMeLight configuration.

        Args:
            working_dir: Working directory path for memory storage
            agent_config: Agent profile configuration containing all settings
                including running config (max_input_length,
                memory_compact_ratio, memory_reserve_ratio, etc.)
                and language setting.

        Environment Variables:
            EMBEDDING_API_KEY: API key for embedding service
            EMBEDDING_BASE_URL: Base URL for embedding API
                (default: dashscope)
            EMBEDDING_MODEL_NAME: Name of the embedding model
            EMBEDDING_DIMENSIONS: Embedding vector dimensions
                (default: 1024)
            EMBEDDING_CACHE_ENABLED: Enable embedding cache (default: true)
            EMBEDDING_MAX_CACHE_SIZE: Max cache size (default: 2000)
            EMBEDDING_MAX_INPUT_LENGTH: Max input length (default: 8192)
            EMBEDDING_MAX_BATCH_SIZE: Max batch size (default: 10)
            FTS_ENABLED: Enable full-text search (default: true)
            MEMORY_STORE_BACKEND: Memory backend - auto/local/chroma
                (default: auto)

        Note:
            Vector search is enabled only when both EMBEDDING_API_KEY and
            EMBEDDING_MODEL_NAME are configured.
        """
        # Extract configuration from agent_config
        running_config = agent_config.running
        self._max_input_length = running_config.max_input_length
        self._memory_compact_ratio = running_config.memory_compact_ratio
        self._memory_reserve_ratio = running_config.memory_reserve_ratio
        self._language = agent_config.language

        if not _REME_AVAILABLE:
            logger.warning(
                "reme package not available, memory features will be limited",
            )
            return

        # Use agent runtime config to avoid cross-agent config leakage.
        local_embedding_config = running_config.local_embedding

        # Create embedding adapter and determine mode
        # This handles local backend registration, fallback logic, etc.
        strict_local = self._safe_str(
            "COPAW_STRICT_LOCAL_EMBEDDING",
            "false",
        ).lower() in ("true", "1", "yes")

        self._embedding_adapter = create_embedding_adapter(
            local_config=local_embedding_config,
            strict_local=strict_local,
        )

        # Determine embedding mode and get configurations
        mode_result = self._embedding_adapter.determine_mode()

        # Log embedding mode decision with structured fields per ADR-002
        logger.info(
            "Embedding mode determined",
            extra={
                "embedding_mode": mode_result.mode,
                "effective_embedding_backend": mode_result.mode,
                "vector_enabled": mode_result.vector_enabled,
                "fallback_applied": mode_result.fallback_applied,
                "fallback_reason": mode_result.fallback_reason,
                "local_backend_registered": (
                    self._embedding_adapter.is_local_registered
                ),
                "strict_local_embedding": self._embedding_adapter.strict_local,
            },
        )

        # Get ReMe configurations from adapter
        embedding_model_config = (
            self._embedding_adapter.get_reme_embedding_config()
        )

        # Environment variables for backward compatibility
        # (only used in remote mode)
        fts_enabled = os.environ.get("FTS_ENABLED", "true").lower() == "true"

        # Determine the memory store backend to use
        # "auto" selects based on platform
        # (local for Windows, chroma otherwise)
        memory_store_backend = os.environ.get("MEMORY_STORE_BACKEND", "auto")
        if memory_store_backend == "auto":
            memory_backend = (
                "local" if platform.system() == "Windows" else "chroma"
            )
        else:
            memory_backend = memory_store_backend

        # Build file store config
        default_file_store_config = {
            "backend": memory_backend,
            "store_name": "copaw",
            "vector_enabled": mode_result.vector_enabled,
            "fts_enabled": fts_enabled,
        }

        # Get remote embedding credentials (for ReMeLight compatibility)
        embedding_api_key = self._safe_str("EMBEDDING_API_KEY", "")
        embedding_base_url = self._safe_str("EMBEDDING_BASE_URL", "")

        # Initialize parent ReMeLight class
        # For local mode, we still pass empty API credentials for compatibility
        super().__init__(
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            working_dir=working_dir,
            default_embedding_model_config=embedding_model_config,
            default_file_store_config=default_file_store_config,
        )

        # Store effective mode for later reference
        self._effective_embedding_mode = mode_result.mode
        self._vector_enabled = mode_result.vector_enabled

        self.summary_toolkit = Toolkit()
        self.summary_toolkit.register_tool_function(read_file)
        self.summary_toolkit.register_tool_function(write_file)
        self.summary_toolkit.register_tool_function(edit_file)

        self.chat_model: ChatModelBase | None = None
        self.formatter: FormatterBase | None = None
        self.token_counter = _get_copaw_token_counter(agent_config)
        self._start_lock = asyncio.Lock()

    @property
    def effective_embedding_mode(self) -> str:
        """Get the effective embedding mode.

        Returns:
            The embedding mode: 'local', 'remote', or 'disabled'.
        """
        return getattr(self, "_effective_embedding_mode", "disabled")

    @property
    def vector_enabled(self) -> bool:
        """Check if vector search is enabled.

        Returns:
            True if vector search is enabled.
        """
        return getattr(self, "_vector_enabled", False)

    @property
    def embedding_adapter(self):
        """Get the embedding adapter.

        Returns:
            The embedding adapter instance or None.
        """
        return getattr(self, "_embedding_adapter", None)

    @staticmethod
    def _safe_str(key: str, default: str) -> str:
        """
        Safely retrieve a string value from an environment variable.

        Args:
            key (str): The name of the environment variable to retrieve
            default (str): The default value to return if the variable
            is not set

        Returns:
            str: The value of the environment variable, or the default
            if not set
        """
        return os.environ.get(key, default)

    @staticmethod
    def _safe_int(key: str, default: int) -> int:
        """
        Safely retrieve an integer value from an environment variable.

        This method handles cases where the environment variable is not set
        or contains a non-integer value by returning the specified default.

        Args:
            key (str): The name of the environment variable to retrieve
            default (int): The default value to return on failure or if not set

        Returns:
            int: The integer value of the environment variable,
                or the default

        Note:
            Logs a warning if the value exists but cannot be parsed
            as an integer
        """
        value = os.environ.get(key)
        if value is None:
            return default

        try:
            return int(value)
        except ValueError:
            logger.warning(
                "Invalid int value '%s' for key '%s', using default %s",
                value,
                key,
                default,
            )
            return default

    def prepare_model_formatter(self):
        if self.chat_model is None or self.formatter is None:
            logger.warning("Model and formatter not initialized.")
            chat_model, formatter = create_model_and_formatter()
            if self.chat_model is None:
                self.chat_model = chat_model
            if self.formatter is None:
                self.formatter = formatter

    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        **_kwargs,
    ) -> str:
        """Compact a list of messages into a condensed summary.

        Args:
            messages: List of Msg objects to compact
            previous_summary: Optional previous summary to incorporate
            **_kwargs: Additional keyword arguments (ignored)

        Returns:
            str: Condensed summary of the messages
        """
        self.prepare_model_formatter()

        # pylint: disable=no-member
        return await super().compact_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
            as_token_counter=self.token_counter,
            language=self._language,
            max_input_length=self._max_input_length,
            compact_ratio=self._memory_compact_ratio,
            previous_summary=previous_summary,
        )

    async def summary_memory(self, messages: list[Msg], **_kwargs) -> str:
        """Generate a comprehensive summary of the given messages.

        Uses file operation tools (read_file, write_file, edit_file) to support
        the summarization process.

        Args:
            messages: List of Msg objects to summarize
            **_kwargs: Additional keyword arguments (ignored)

        Returns:
            str: Comprehensive summary of the messages
        """
        self.prepare_model_formatter()

        # pylint: disable=no-member
        return await super().summary_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
            as_token_counter=self.token_counter,
            toolkit=self.summary_toolkit,
            language=self._language,
            max_input_length=self._max_input_length,
            compact_ratio=self._memory_compact_ratio,
        )

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        if not self._started:
            async with self._start_lock:
                if not self._started:
                    logger.warning(
                        "ReMe is not started, report github issue!",
                    )
                    await self.start()

        # pylint: disable=no-member
        return await super().memory_search(
            query=query,
            max_results=max_results,
            min_score=min_score,
        )

    def get_in_memory_memory(self, **_kwargs):
        """Retrieve in-memory memory content.

        Args:
            **kwargs: Additional keyword arguments (passed to parent)

        Returns:
            In-memory memory with token counting
        """
        # pylint: disable=no-member
        return super().get_in_memory_memory(
            as_token_counter=self.token_counter,
        )

    def encode_text(self, texts: list[str]) -> list[list[float]]:
        """Encode texts using local embedder if available.

        Args:
            texts: List of text strings to encode

        Returns:
            List of embedding vectors
        """
        # pylint: disable=no-member
        # Note: _local_embedder is provided by ReMeLight parent class
        if hasattr(self, "_local_embedder") and self._local_embedder:
            return self._local_embedder.encode_text(texts)
        # Fall back to parent class (remote API)
        if self.embedding_model:
            return self.embedding_model.encode(texts)
        raise RuntimeError(
            "No embedding provider. "
            "Enable local embedding or set EMBEDDING_API_KEY.",
        )
