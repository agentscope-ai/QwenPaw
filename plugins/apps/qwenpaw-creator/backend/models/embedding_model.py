# -*- coding: utf-8 -*-
"""DashScope native multimodal-embedding thin client.

Creator-native rewrite of the upstream video-memory embedding transport
(手法 A): the vendored index keeps only local math, while every HTTP call
goes through this client with the ``creator_embedding_model`` config tree.
The native endpoint rejects large batches, so inputs are split and each
batch retries throttling errors with capped exponential backoff.
"""

from __future__ import annotations

import asyncio
import random

import httpx

from models import config as model_config
from utils.exceptions import ModelError
from utils.logger import setup_logger

logger = setup_logger("model.embedding")

# Native endpoint rejects large batches; cap per-request size.
MAX_BATCH_SIZE = 10
DEFAULT_DIMENSION = 2560

_RETRYABLE_STATUS = {429, 500, 502, 503}
_MAX_RETRIES = 6
_RETRY_BASE_SECONDS = 2.0


def _embedding_url(base_url: str) -> str:
    suffix = "/services/embeddings/multimodal-embedding/multimodal-embedding"
    base = base_url.rstrip("/")
    return base if base.endswith(suffix) else f"{base}{suffix}"


async def _post_batch(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    model_name: str,
    texts: list[str],
    dimension: int,
) -> list[list[float]]:
    payload = {
        "model": model_name,
        "input": {"contents": [{"text": text} for text in texts]},
        "parameters": {"dimension": dimension},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            last_error = exc
            response = None
        if response is not None:
            if response.status_code == 200:
                data = response.json()
                embeddings = (data.get("output") or {}).get("embeddings")
                if not isinstance(embeddings, list) or len(embeddings) != len(
                    texts,
                ):
                    raise ModelError(
                        "embedding response does not match batch size",
                        model_name=model_name,
                    )
                return [item["embedding"] for item in embeddings]
            if response.status_code not in _RETRYABLE_STATUS:
                raise ModelError(
                    "embedding request failed with status "
                    f"{response.status_code}: {response.text[:300]}",
                    model_name=model_name,
                )
            last_error = ModelError(
                f"embedding HTTP {response.status_code}: "
                f"{response.text[:200]}",
                model_name=model_name,
            )
        if attempt == _MAX_RETRIES:
            break
        delay = min(
            _RETRY_BASE_SECONDS * (2 ** min(attempt, 5)) + random.random(),
            60.0,
        )
        logger.warning(
            "embedding batch retry %d/%d in %.1fs: %s",
            attempt + 1,
            _MAX_RETRIES,
            delay,
            last_error,
        )
        await asyncio.sleep(delay)
    raise ModelError(
        f"embedding request failed after {_MAX_RETRIES} retries: "
        f"{last_error}",
        model_name=model_name,
    )


async def embed(
    inputs: list[str],
    *,
    dimension: int = DEFAULT_DIMENSION,
    timeout: float = 120.0,
) -> list[list[float]]:
    """Embed texts via the configured DashScope multimodal-embedding API.

    Inputs are split into provider-sized batches; each batch retries
    throttling with exponential backoff. Returns one vector per input.
    """
    if not inputs:
        return []
    api_key = model_config.get_embedding_api_key()
    model_name = model_config.get_embedding_model_name()
    if not api_key:
        raise ModelError(
            "creator_embedding_model.api_key, EMBEDDING_API_KEY, or the "
            "reused VLM key is required",
            model_name=model_name,
        )
    url = _embedding_url(model_config.get_embedding_base_url())
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for start in range(0, len(inputs), MAX_BATCH_SIZE):
            batch = inputs[start : start + MAX_BATCH_SIZE]
            vectors.extend(
                await _post_batch(
                    client,
                    url,
                    api_key,
                    model_name,
                    batch,
                    dimension,
                ),
            )
    return vectors
