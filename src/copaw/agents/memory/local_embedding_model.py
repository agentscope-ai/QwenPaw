# -*- coding: utf-8 -*-
"""Local embedding model adapter for ReMe integration.

This module provides a ReMe-compatible local embedding model that uses
CoPaw's existing LocalEmbedder to generate embeddings without requiring
external API calls.
"""

import asyncio
import logging
from typing import Optional

from reme.core.embedding import BaseEmbeddingModel

from copaw.config.config import LocalEmbeddingConfig
from copaw.agents.memory.local_embedder import LocalEmbedder

logger = logging.getLogger(__name__)


class LocalEmbeddingModel(BaseEmbeddingModel):
    """ReMe-compatible local embedding model using LocalEmbedder.

    This class bridges CoPaw's LocalEmbedder with ReMe's BaseEmbeddingModel
    interface to enable local embedding in memory search.

    The LocalEmbedder supports both multimodal (Qwen3-VL) and text-only
    (BGE/GTE) models using transformers native interface.

    Example:
        >>> from copaw.config.config import LocalEmbeddingConfig
        >>> config = LocalEmbeddingConfig(
        ...     enabled=True,
        ...     model_id="BAAI/bge-small-zh",
        ... )
        >>> model = LocalEmbeddingModel(
        ...     model_name="BAAI/bge-small-zh",
        ...     dimensions=512,
        ...     local_embedding_config=config,
        ... )
        >>> embeddings = await model.get_embeddings(["Hello world"])
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: str = "",
        dimensions: int = 1024,
        use_dimensions: bool = False,
        max_batch_size: int = 10,
        max_retries: int = 3,
        raise_exception: bool = True,
        max_input_length: int = 8192,
        cache_dir: str = ".reme",
        max_cache_size: int = 2000,
        enable_cache: bool = True,
        **kwargs,
    ):
        """Initialize the local embedding model adapter.

        Args:
            api_key: Not used for local models (for API compatibility).
            base_url: Not used for local models (for API compatibility).
            model_name: Name of the embedding model
                (model_id in LocalEmbeddingConfig).
            dimensions: Expected dimensions of the embeddings.
            use_dimensions: Whether to use dimensions parameter
                (not used locally).
            max_batch_size: Maximum batch size for embedding requests.
            max_retries: Maximum number of retry attempts on failure.
            raise_exception: Whether to raise exceptions on failure.
            max_input_length: Maximum input text length.
            cache_dir: Directory for caching embeddings.
            max_cache_size: Maximum number of embeddings to cache in memory.
            enable_cache: Whether to enable embedding cache.
            **kwargs: Additional keyword arguments, including:
                - local_embedding_config: LocalEmbeddingConfig object
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            dimensions=dimensions,
            use_dimensions=use_dimensions,
            max_batch_size=max_batch_size,
            max_retries=max_retries,
            raise_exception=raise_exception,
            max_input_length=max_input_length,
            cache_dir=cache_dir,
            max_cache_size=max_cache_size,
            enable_cache=enable_cache,
            **kwargs,
        )

        # Extract or create local embedding configuration
        local_config = kwargs.get("local_embedding_config")
        if local_config is None:
            # Create default config based on model_name
            local_config = LocalEmbeddingConfig(
                enabled=True,
                model_id=model_name or "BAAI/bge-small-zh",
            )
        elif isinstance(local_config, dict):
            # Convert dict to config object
            local_config = LocalEmbeddingConfig(**local_config)

        self._local_config: LocalEmbeddingConfig = local_config

        # Initialize embedder (lazy initialization happens in LocalEmbedder)
        self._embedder: Optional[LocalEmbedder] = None
        self._embedder_lock = asyncio.Lock()

    async def _get_embedder(self) -> LocalEmbedder:
        """Get or create the LocalEmbedder instance (thread-safe).

        Returns:
            The LocalEmbedder instance.
        """
        if self._embedder is None:
            async with self._embedder_lock:
                if self._embedder is None:
                    self._embedder = LocalEmbedder(self._local_config)
        return self._embedder

    def _get_embeddings_sync(
        self,
        input_text: list[str],
        **kwargs,  # pylint: disable=unused-argument
    ) -> list[list[float]]:
        """Synchronous embedding generation.

        Args:
            input_text: List of text strings to encode.
            **kwargs: Additional arguments (ignored).

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If embedding generation fails.
        """
        try:
            # Create embedder if not exists (sync version)
            if self._embedder is None:
                self._embedder = LocalEmbedder(self._local_config)

            logger.debug(
                "Generating embeddings for %d texts",
                len(input_text),
            )
            embeddings = self._embedder.encode_text(input_text)
            logger.debug("Generated %d embeddings", len(embeddings))

            # Validate dimensions match expected
            if embeddings and len(embeddings[0]) != self.dimensions:
                logger.warning(
                    "Embedding dimensions mismatch: expected %d, "
                    "got %d. Adjusting...",
                    self.dimensions,
                    len(embeddings[0]),
                )
                embeddings = [
                    self._validate_and_adjust_embedding(emb)
                    for emb in embeddings
                ]

            return embeddings

        except (RuntimeError, ValueError, OSError) as e:
            logger.error("Failed to generate embeddings: %s", e)
            if self.raise_exception:
                raise
            return [[] for _ in input_text]

    async def _get_embeddings(
        self,
        input_text: list[str],
        **kwargs,  # pylint: disable=unused-argument
    ) -> list[list[float]]:
        """Async embedding generation (runs sync in thread pool).

        Args:
            input_text: List of text strings to encode.
            **kwargs: Additional arguments (ignored).

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If embedding generation fails.
        """
        try:
            # Get or create embedder
            embedder = await self._get_embedder()

            # Run the synchronous encode_text in a thread pool
            logger.debug(
                "Generating async embeddings for %d texts",
                len(input_text),
            )
            embeddings = await asyncio.to_thread(
                embedder.encode_text,
                input_text,
            )
            logger.debug("Generated %d async embeddings", len(embeddings))

            # Validate dimensions match expected
            if embeddings and len(embeddings[0]) != self.dimensions:
                logger.warning(
                    "Embedding dimensions mismatch: expected %d, "
                    "got %d. Adjusting...",
                    self.dimensions,
                    len(embeddings[0]),
                )
                embeddings = [
                    self._validate_and_adjust_embedding(emb)
                    for emb in embeddings
                ]

            return embeddings

        except (RuntimeError, ValueError, OSError) as e:
            logger.error("Failed to generate async embeddings: %s", e)
            if self.raise_exception:
                raise
            return [[] for _ in input_text]

    async def start(self) -> None:
        """Asynchronously initialize resources and load cache.

        This method pre-loads the embedding model to avoid lazy loading
        during the first embedding request.
        """
        await super().start()

        # Pre-load the model
        try:
            _ = await self._get_embedder()
            # Trigger model loading by calling encode_text with empty list
            # or we could add a specific load method to LocalEmbedder
            logger.info(
                "Local embedding model initialized: %s",
                self._local_config.model_id,
            )
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to pre-load local embedding model: %s", e)

    def start_sync(self) -> None:
        """Synchronously initialize resources and load cache.

        This method pre-loads the embedding model to avoid lazy loading
        during the first embedding request.
        """
        super().start_sync()

        # Pre-load the model
        try:
            if self._embedder is None:
                self._embedder = LocalEmbedder(self._local_config)
            logger.info(
                "Local embedding model initialized: %s",
                self._local_config.model_id,
            )
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to pre-load local embedding model: %s", e)

    async def close(self) -> None:
        """Asynchronously release resources and close connections."""
        await super().close()
        if self._embedder is not None:
            self._embedder.unload()
            self._embedder = None
        logger.info("Local embedding model resources released")

    def close_sync(self) -> None:
        """Synchronously release resources and close connections."""
        super().close_sync()
        if self._embedder is not None:
            self._embedder.unload()
            self._embedder = None
        logger.info("Local embedding model resources released")


__all__ = [
    "LocalEmbeddingModel",
]
