# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Memory Manager for CoPaw agents.

Extends ReMeLight to provide memory management capabilities including:
- Message compaction with configurable ratio
- Memory summarization with tool support
- Vector and full-text search integration
- Embedding configuration from environment variables
"""
import logging
import os
import platform

from agentscope.formatter import FormatterBase
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.tool import Toolkit
from copaw.agents.model_factory import create_model_and_formatter
from copaw.agents.tools import read_file, write_file, edit_file
from copaw.agents.utils import _get_token_counter
from copaw.config import load_config
from .local_embedder import LocalEmbedder

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
        max_input_length: int = 128 * 1024,
        memory_compact_ratio: float = 0.7,
        memory_reserve_ratio: float = 0.1,
        language: str = "zh",
    ):
        """Initialize MemoryManager with ReMeLight configuration.

        Args:
            working_dir: Working directory path for memory storage
            max_input_length: Maximum input length in tokens for context
                window (default: 128K = 131072)
            memory_compact_ratio: Ratio for memory compaction
                (default: 0.7)
            memory_reserve_ratio: Ratio for memory reserve
                (default: 0.1)
            language: Language for memory operations (default: "zh")

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
        # Store configuration parameters
        self._max_input_length = max_input_length
        self._memory_compact_ratio = memory_compact_ratio
        self._memory_reserve_ratio = memory_reserve_ratio
        self._language = language

        if not _REME_AVAILABLE:
            logger.warning(
                "reme package not available, memory features will be limited",
            )
            return

        # Load config for local embedding settings
        config = load_config()
        local_embedding_config = config.agents.running.local_embedding

        # Environment variables (for backward compatibility)
        embedding_api_key = self._safe_str("EMBEDDING_API_KEY", "")
        embedding_base_url = self._safe_str(
            "EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
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

        # Initialize local embedder if enabled
        self._local_embedder: LocalEmbedder | None = None
        local_embedding_enabled = local_embedding_config.enabled

        if local_embedding_enabled:
            try:
                self._local_embedder = LocalEmbedder(local_embedding_config)
                logger.info(f"Local embedding enabled with model: {local_embedding_config.model_id}")
            except Exception as e:
                logger.error(f"Failed to initialize local embedder: {e}")
                local_embedding_enabled = False

        # Determine if vector search should be enabled based on configuration
        # Priority: local embedding > remote API > disabled
        vector_enabled = local_embedding_enabled or (
            bool(embedding_api_key) and bool(embedding_model_name)
        )
        
        if vector_enabled:
            if self._local_embedder:
                logger.info("Vector search enabled with local embedding model.")
            else:
                logger.info("Vector search enabled with remote API.")
        else:
            logger.warning(
                "Vector search disabled. Memory search functionality "
                "will be restricted. "
                "To enable, configure local embedding in settings or set: "
                "EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL_NAME.",
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
        self.token_counter = _get_token_counter()

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

        return await super().compact_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
            token_counter=self.token_counter,
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
        return await super().summary_memory(
            messages=messages,
            as_llm=self.chat_model,
            as_llm_formatter=self.formatter,
            token_counter=self.token_counter,
            toolkit=self.summary_toolkit,
            language=self._language,
            max_input_length=self._max_input_length,
            compact_ratio=self._memory_compact_ratio,
        )

    def get_in_memory_memory(self, **_kwargs):
        """Retrieve in-memory memory content.

        Args:
            **kwargs: Additional keyword arguments (passed to parent)

        Returns:
            The in-memory memory content with token counting support
        """
        return super().get_in_memory_memory(token_counter=self.token_counter)

    def encode_text(self, texts: list[str]) -> list[list[float]]:
        """Encode texts to embeddings using local embedder.
        
        This method provides embeddings for vector memory search.
        Uses local embedding model if enabled, otherwise falls back to
        parent class behavior (remote API).
        
        Args:
            texts: List of text strings to encode
            
        Returns:
            List of embedding vectors
            
        Raises:
            RuntimeError: If no embedding provider is available
        """
        if self._local_embedder is not None:
            return self._local_embedder.encode_text(texts)
        
        # Fall back to parent class (remote API) if available
        if hasattr(self, 'embedding_model') and self.embedding_model is not None:
            return self.embedding_model.encode(texts)
        
        raise RuntimeError(
            "No embedding provider available. "
            "Please enable local embedding in settings or configure EMBEDDING_API_KEY."
        )

    def get_local_embedder_info(self) -> dict | None:
        """Get information about local embedder if enabled.
        
        Returns:
            Dictionary with model info, or None if not enabled
        """
        if self._local_embedder is None:
            return None
        return self._local_embedder.get_model_info()
