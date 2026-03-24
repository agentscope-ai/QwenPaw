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
import inspect
import json
import logging
import os
import platform
import uuid
from typing import TYPE_CHECKING

from agentscope.formatter import FormatterBase
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.tool import Toolkit, ToolResponse

from copaw.agents.model_factory import create_model_and_formatter
from copaw.agents.tools import read_file, write_file, edit_file
from copaw.agents.utils import get_copaw_token_counter
from copaw.config import load_config
from copaw.config.config import load_agent_config

if TYPE_CHECKING:
    from copaw.config.config import AgentProfileConfig

logger = logging.getLogger(__name__)

# Try to import reme, log warning if it fails
try:
    from reme.reme_light import ReMeLight

    _REME_AVAILABLE = True

except ImportError as e:
    _REME_AVAILABLE = False
    logger.warning(f"reme package not installed. {e}")

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
        agent_id: str | None = None,
    ):
        """Initialize MemoryManager with ReMeLight configuration.

        Args:
            working_dir: Working directory path for memory storage
            agent_config: Agent profile configuration containing all settings
                including running config (max_input_length,
                memory_compact_ratio, memory_reserve_ratio, etc.)
                and language setting.
            agent_id: Optional agent identifier for hot-reload callers that
                resolve config from memory_manager.agent_id.

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
        self.agent_id = agent_id or agent_config.id

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

        embedding_api_key = self._safe_str("EMBEDDING_API_KEY", "")
        embedding_base_url = self._safe_str("EMBEDDING_BASE_URL", "")
        embedding_model_name = self._safe_str("EMBEDDING_MODEL_NAME", "")
        embedding_dimensions = self._safe_int("EMBEDDING_DIMENSIONS", 1024)
        embedding_cache_enabled = (
            self._safe_str("EMBEDDING_CACHE_ENABLED", "true").lower() == "true"
        )
        embedding_max_cache_size = self._safe_int(
            "EMBEDDING_MAX_CACHE_SIZE",
            2000,
        )
        embedding_max_input_length = self._safe_int(
            "EMBEDDING_MAX_INPUT_LENGTH",
            8192,
        )
        embedding_max_batch_size = self._safe_int(
            "EMBEDDING_MAX_BATCH_SIZE",
            10,
        )

        # Determine if vector search should be enabled based on configuration
        # Vector search requires either an API key or a local model name
        vector_enabled = (
            bool(embedding_api_key)
            and bool(embedding_model_name)
            and bool(embedding_base_url)
        )
        if vector_enabled:
            logger.info(
                f"Vector search enabled. "
                f"embedding_api_key={embedding_api_key[:5]}... "
                f"embedding_model_name={embedding_model_name} "
                f"embedding_base_url={embedding_base_url} ",
            )
        else:
            logger.warning(
                "Vector search disabled. Memory search functionality "
                "will be restricted. "
                "To enable, configure: "
                f"EMBEDDING_API_KEY={embedding_api_key[:5]}... "
                f"EMBEDDING_BASE_URL={embedding_base_url} "
                f"EMBEDDING_MODEL_NAME={embedding_model_name} ",
            )

        # Check if full-text search (FTS) is enabled via environment variable
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

        # Initialize parent ReMeCopaw class
        super().__init__(
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            working_dir=working_dir,
            default_embedding_model_config={
                "model_name": embedding_model_name,
                "dimensions": embedding_dimensions,
                "enable_cache": embedding_cache_enabled,
                "use_dimensions": False,
                "max_cache_size": embedding_max_cache_size,
                "max_input_length": embedding_max_input_length,
                "max_batch_size": embedding_max_batch_size,
            },
            default_file_store_config={
                "backend": memory_backend,
                "store_name": "copaw",
                "vector_enabled": vector_enabled,
                "fts_enabled": fts_enabled,
            },
        )

        self.summary_toolkit = Toolkit()
        self.summary_toolkit.register_tool_function(read_file)
        self.summary_toolkit.register_tool_function(write_file)
        self.summary_toolkit.register_tool_function(edit_file)

        self.chat_model: ChatModelBase | None = None
        self.formatter: FormatterBase | None = None
        self.token_counter = get_copaw_token_counter(agent_config)
        self._start_lock = asyncio.Lock()

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
            chat_model, formatter = create_model_and_formatter(self.agent_id)
            if self.chat_model is None:
                self.chat_model = chat_model
            if self.formatter is None:
                self.formatter = formatter

    @staticmethod
    def _token_counter_kwarg(method_name: str) -> str:
        """Return the token counter kwarg name supported by the installed ReMe."""
        try:
            method = getattr(ReMeLight, method_name)
            parameters = inspect.signature(method).parameters
        except (AttributeError, TypeError, ValueError):
            return "token_counter"
        return (
            "token_counter"
            if "token_counter" in parameters
            else "as_token_counter"
        )

    async def check_context(
        self,
        messages: list[Msg],
        memory_compact_threshold: int,
        memory_compact_reserve: int = 10000,
        token_counter=None,
        as_token_counter=None,
    ):
        """Compatibility wrapper for ReMe check_context across versions."""
        effective_token_counter = (
            token_counter if token_counter is not None else as_token_counter
        )
        token_counter_kwarg = self._token_counter_kwarg("check_context")
        return await super().check_context(
            messages=messages,
            memory_compact_threshold=memory_compact_threshold,
            memory_compact_reserve=memory_compact_reserve,
            **{token_counter_kwarg: effective_token_counter},
        )

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
            str: Condensed summary of the messages, empty string if invalid
        """

        self.prepare_model_formatter()

        token_counter_kwarg = self._token_counter_kwarg("compact_memory")
        agent_config = load_agent_config(self.agent_id)
        token_counter = get_copaw_token_counter(agent_config)
        add_thinking_block = agent_config.running.compact_with_thinking_block
        workspace_dir = agent_config.workspace_dir

    token_counter_kwarg = self._token_counter_kwarg("compact_memory")

        result = await super().compact_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
        **{token_counter_kwarg: token_counter},
        language=agent_config.language,
        max_input_length=agent_config.running.max_input_length,
        compact_ratio=agent_config.running.memory_compact_ratio,
            previous_summary=previous_summary,
            return_dict=True,
            add_thinking_block=add_thinking_block,
        )

        # Handle unexpected str return (should be dict)
        if isinstance(result, str):
            logger.error(
                f"compact_memory returned str instead of dict, "
                f"result: {result[:200]}... "
                "Please install the latest reme package.",
            )
            return result

        # result is dict
        is_valid: bool = result.get("is_valid", True)
        if not is_valid:
            # Save invalid result to file
            unique_id = uuid.uuid4().hex[:8]
            filename = f"compact_invalid_{unique_id}.json"
            filepath = os.path.join(workspace_dir, filename)

            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logger.error(
                    f"Invalid compact result saved to {filepath}. "
                    f"user_msg: {result.get('user_message', '')[:200]}..., "
                    "history_compact: "
                    f"{result.get('history_compact', '')[:200]}...",
                )
                logger.error(
                    "Please upload the log to the community: "
                    "https://github.com/agentscope-ai/CoPaw/issues",
                )
            except Exception as _e:
                logger.error(f"Failed to save invalid compact result: {_e}")

            return ""

        return result.get("history_compact", "")

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

        token_counter_kwarg = self._token_counter_kwarg("summary_memory")
        agent_config = load_agent_config(self.agent_id)
        token_counter = get_copaw_token_counter(agent_config)
        add_thinking_block = agent_config.running.compact_with_thinking_block
        user_tz = load_config().user_timezone or None

    token_counter_kwarg = self._token_counter_kwarg("summary_memory")

        return await super().summary_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
        **{token_counter_kwarg: token_counter},
            toolkit=self.summary_toolkit,
            language=agent_config.language,
            max_input_length=agent_config.running.max_input_length,
            compact_ratio=agent_config.running.memory_compact_ratio,
            timezone=user_tz,
            add_thinking_block=add_thinking_block,
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
            The in-memory memory content with token counting support
        """
        token_counter_kwarg = self._token_counter_kwarg(
            "get_in_memory_memory",
        )
        return super().get_in_memory_memory(
            **{token_counter_kwarg: self.token_counter},
        )
