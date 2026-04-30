# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from typing import Any

import httpx


_embedding_cache: dict[str, list[list[float]]] = {}


def has_usable_embedding_model(config: dict[str, Any] | None) -> bool:
    if not isinstance(config, dict):
        return False
    return bool(str(config.get("base_url") or "").strip() and str(config.get("model_name") or "").strip())


def normalize_embedding_endpoint(base_url: str) -> str:
    trimmed = str(base_url or "").strip().rstrip("/")
    if not trimmed:
        return ""
    if trimmed.endswith("/embeddings"):
        return trimmed
    return f"{trimmed}/embeddings"


def _prepare_input(text: str, max_input_length: int) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    limit = max(1, int(max_input_length or 8192))
    return normalized[:limit]


def _build_cache_key(config: dict[str, Any], texts: list[str]) -> str:
    parts = [str(config.get("base_url")), str(config.get("model_name")), str(config.get("dimensions"))]
    parts.extend(texts)
    return "::".join(parts)


def embed_texts(config: dict[str, Any], texts: list[str]) -> list[list[float]]:
    endpoint = normalize_embedding_endpoint(str(config.get("base_url") or ""))
    model_name = str(config.get("model_name") or "").strip()
    if not endpoint or not model_name:
        raise ValueError("Embedding model is not configured.")

    max_input_length = int(config.get("max_input_length") or 8192)
    max_batch_size = int(config.get("max_batch_size") or 16)
    enable_cache = bool(config.get("enable_cache", True))
    max_cache_size = int(config.get("max_cache_size") or 1000)

    prepared = [_prepare_input(text, max_input_length) for text in texts]
    if not prepared:
        return []

    # Evict oldest cache entries if over limit
    if enable_cache and len(_embedding_cache) > max_cache_size:
        keys = list(_embedding_cache.keys())
        for k in keys[: len(keys) - max_cache_size]:
            _embedding_cache.pop(k, None)

    headers = {"Content-Type": "application/json"}
    api_key = str(config.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    all_embeddings: list[list[float]] = [None] * len(prepared)  # type: ignore[list-item]

    # Process in batches
    for batch_start in range(0, len(prepared), max_batch_size):
        batch = prepared[batch_start : batch_start + max_batch_size]
        batch_indices = list(range(batch_start, batch_start + len(batch)))

        cache_key = _build_cache_key(config, batch) if enable_cache else ""
        if enable_cache and cache_key in _embedding_cache:
            cached = _embedding_cache[cache_key]
            for idx, emb in zip(batch_indices, cached):
                all_embeddings[idx] = emb
            continue

        request_payload: dict[str, Any] = {
            "input": batch,
            "model": model_name,
        }
        if config.get("use_dimensions"):
            request_payload["dimensions"] = int(config.get("dimensions") or 0)

        timeout = httpx.Timeout(60.0, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(endpoint, headers=headers, json=request_payload)
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data") or []
        if len(data) != len(batch):
            raise ValueError("Embedding response size does not match the request.")

        batch_embeddings: list[list[float]] = []
        for item in data:
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise ValueError("Embedding response is missing a usable vector.")
            batch_embeddings.append([float(value) for value in vector])

        if enable_cache:
            _embedding_cache[cache_key] = batch_embeddings

        for idx, emb in zip(batch_indices, batch_embeddings):
            all_embeddings[idx] = emb

    return all_embeddings


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)