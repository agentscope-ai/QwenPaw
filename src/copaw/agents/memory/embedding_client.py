# -*- coding: utf-8 -*-
"""ADR-003 ReMe-facing embedding client with backend factory."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx
from reme.core.embedding import BaseEmbeddingModel

from copaw.agents.memory.embedding.backends import (
    EmbeddingBackend,
    OllamaEmbeddingBackend,
    TransformersEmbeddingBackend,
)
from copaw.config.config import LocalEmbeddingConfig

logger = logging.getLogger(__name__)


class EmbeddingClient(BaseEmbeddingModel):
    """Single ReMe-facing embedding entrypoint for local/ollama backends."""

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
        **kwargs: Any,
    ) -> None:
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
        self._kwargs = kwargs
        self._backend: Optional[EmbeddingBackend] = None
        self._backend_lock = asyncio.Lock()

    def _resolve_backend_type(self) -> str:
        explicit = self._kwargs.get("backend_type")
        if isinstance(explicit, str) and explicit in (
            "transformers",
            "ollama",
            "openai",
        ):
            return explicit

        # Backward compatibility: old local path passed local_embedding_config
        # without backend_type.
        if self._kwargs.get("local_embedding_config") is not None:
            return "transformers"

        # This class should only be used for local/ollama backends.
        raise ValueError(
            "EmbeddingClient requires explicit backend_type "
            "('transformers' or 'ollama')",
        )

    def _create_backend(self) -> EmbeddingBackend:
        backend_type = self._resolve_backend_type()

        if backend_type == "transformers":
            local_config_raw = self._kwargs.get("local_embedding_config")
            if isinstance(local_config_raw, LocalEmbeddingConfig):
                local_config = local_config_raw
            elif isinstance(local_config_raw, dict):
                local_config = LocalEmbeddingConfig(**local_config_raw)
            else:
                local_config = LocalEmbeddingConfig(
                    enabled=True,
                    model_id=self.model_name or "BAAI/bge-small-zh",
                )
            return TransformersEmbeddingBackend(local_config)

        if backend_type == "ollama":
            return OllamaEmbeddingBackend(
                base_url=self.base_url or "",
                model_name=self.model_name,
                dimensions=self.dimensions,
            )

        raise ValueError(
            f"Unsupported backend_type for EmbeddingClient: {backend_type}",
        )

    async def _get_backend(self) -> EmbeddingBackend:
        if self._backend is None:
            async with self._backend_lock:
                if self._backend is None:
                    self._backend = self._create_backend()
        return self._backend

    def _get_embeddings_sync(
        self,
        input_text: list[str],
        **_kwargs: Any,
    ) -> list[list[float]]:
        try:
            if self._backend is None:
                self._backend = self._create_backend()
            truncated = self._truncate_texts(input_text)
            embeddings = self._backend.encode_text(truncated)
            if embeddings and len(embeddings[0]) != self.dimensions:
                embeddings = [
                    self._validate_and_adjust_embedding(emb)
                    for emb in embeddings
                ]
            return embeddings
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as e:
            logger.error("EmbeddingClient sync embedding failed: %s", e)
            if self.raise_exception:
                raise
            return [[] for _ in input_text]

    async def _get_embeddings(
        self,
        input_text: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        _ = kwargs
        backend = await self._get_backend()
        try:
            truncated = self._truncate_texts(input_text)
            embeddings = await asyncio.to_thread(
                backend.encode_text,
                truncated,
            )
            if embeddings and len(embeddings[0]) != self.dimensions:
                embeddings = [
                    self._validate_and_adjust_embedding(emb)
                    for emb in embeddings
                ]
            return embeddings
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as e:
            logger.error("EmbeddingClient async embedding failed: %s", e)
            if self.raise_exception:
                raise
            return [[] for _ in input_text]

    async def close(self) -> None:
        await super().close()
        if self._backend is not None:
            self._backend.unload()
            self._backend = None

    def close_sync(self) -> None:
        super().close_sync()
        if self._backend is not None:
            self._backend.unload()
            self._backend = None


__all__ = ["EmbeddingClient"]
