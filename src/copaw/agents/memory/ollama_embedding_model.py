# -*- coding: utf-8 -*-
"""Ollama embedding backend for ReMe (``backend_type=ollama`` in config)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

import httpx
from reme.core.embedding import BaseEmbeddingModel

logger = logging.getLogger(__name__)


class OllamaEmbeddingModel(BaseEmbeddingModel):
    """ReMe-compatible embeddings via Ollama ``/api/embed``."""

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

    def _normalize_base(self) -> str:
        raw = (self.base_url or "").strip()
        if not raw:
            return "http://127.0.0.1:11434"
        normalized = raw.rstrip("/")
        # Users may copy OpenAI-compatible Ollama URLs like
        # http://host:11434/v1 or http://host:11434/api.
        # ReMe ollama backend always calls /api/embed directly.
        for suffix in ("/v1", "/api"):
            if normalized.lower().endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        return normalized.rstrip("/")

    def _embed_sync(self, input_text: List[str]) -> List[List[float]]:
        if not input_text:
            return []
        base = self._normalize_base()
        url = f"{base}/api/embed"
        payload: dict = {"model": self.model_name, "input": input_text}
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if "embeddings" in data:
            out = data["embeddings"]
            if isinstance(out, list):
                return [list(map(float, e)) for e in out]
        emb = data.get("embedding")
        if emb is not None:
            return [list(map(float, emb))]
        raise RuntimeError(
            f"Unexpected Ollama /api/embed response keys: {data.keys()}",
        )

    def _get_embeddings_sync(
        self,
        input_text: List[str],
        **_kwargs: Any,
    ) -> List[List[float]]:
        try:
            truncated = self._truncate_texts(input_text)
            embeddings = self._embed_sync(truncated)
            if embeddings and len(embeddings[0]) != self.dimensions:
                embeddings = [
                    self._validate_and_adjust_embedding(e) for e in embeddings
                ]
            return embeddings
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as e:
            logger.error("Ollama embedding failed: %s", e)
            if self.raise_exception:
                raise
            return [[] for _ in input_text]

    async def _get_embeddings(
        self,
        input_text: List[str],
        **kwargs: Any,
    ) -> List[List[float]]:
        return await asyncio.to_thread(
            self._get_embeddings_sync,
            input_text,
            **kwargs,
        )
