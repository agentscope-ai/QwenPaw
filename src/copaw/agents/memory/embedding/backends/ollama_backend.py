# -*- coding: utf-8 -*-
"""Ollama embedding backend wrapper."""

from __future__ import annotations

from typing import Any, List

import httpx

from copaw.agents.memory.embedding.backends.base import EmbeddingBackend


class OllamaEmbeddingBackend(EmbeddingBackend):
    """Embedding backend for Ollama /api/embed."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        dimensions: int,
    ) -> None:
        self._base_url = self._normalize_base(base_url)
        self._model_name = model_name
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @staticmethod
    def _normalize_base(raw: str) -> str:
        normalized = (raw or "").strip().rstrip("/")
        if not normalized:
            normalized = "http://127.0.0.1:11434"
        for suffix in ("/v1", "/api"):
            if normalized.lower().endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        return normalized.rstrip("/")

    def encode_text(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        url = f"{self._base_url}/api/embed"
        payload: dict[str, Any] = {"model": self._model_name, "input": texts}

        with httpx.Client(timeout=120.0, trust_env=False) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        if "embeddings" in data and isinstance(data["embeddings"], list):
            return [list(map(float, emb)) for emb in data["embeddings"]]
        if "embedding" in data and data["embedding"] is not None:
            return [list(map(float, data["embedding"]))]

        raise RuntimeError(
            f"Unexpected Ollama /api/embed response keys: {data.keys()}",
        )
