# -*- coding: utf-8 -*-
"""AgentScope embedding model construction and connectivity checks."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Any

from agentscope.credential import (
    DashScopeCredential,
    GeminiCredential,
    OllamaCredential,
    OpenAICredential,
)
from agentscope.embedding import EmbeddingModelBase

from qwenpaw.config.config import EmbeddingModelConfig

from .reme_config import _embedding_credential, _is_embedding_enabled

_CREDENTIAL_TYPES = {
    "openai": OpenAICredential,
    "dashscope": DashScopeCredential,
    "dashscope_multimodal": DashScopeCredential,
    "gemini": GeminiCredential,
    "ollama": OllamaCredential,
}

_TEST_TEXT = "QwenPaw embedding connection test"


@dataclass(frozen=True)
class EmbeddingTestResult:
    """Result of one real embedding provider request."""

    success: bool
    configured_dimensions: int
    actual_dimensions: int | None
    latency_ms: int
    message: str


def create_embedding_model(
    config: EmbeddingModelConfig,
    *,
    max_retries: int = 3,
) -> EmbeddingModelBase[Any]:
    """Create the AgentScope embedding object represented by ``config``."""
    if not _is_embedding_enabled(config):
        raise ValueError(
            "Embedding model name and provider credentials are required",
        )

    credential_type = _CREDENTIAL_TYPES.get(config.backend)
    if credential_type is None:
        raise ValueError(f"Unsupported embedding backend: {config.backend}")

    credential = credential_type(**_embedding_credential(config))
    model_type = credential_type.get_embedding_model_class()
    if model_type is None:
        raise ValueError(
            f"{credential_type.__name__} does not support embeddings",
        )

    kwargs: dict[str, Any] = {
        "credential": credential,
        "model": config.model_name.strip(),
        "dimensions": config.dimensions,
        "parameters": None,
        "context_size": config.max_input_length,
        "max_retries": max_retries,
    }
    if config.backend == "openai":
        kwargs["pass_dimensions"] = config.use_dimensions
    return model_type(**kwargs)


async def test_embedding_model(
    config: EmbeddingModelConfig,
    *,
    timeout: float | None = None,
) -> tuple[EmbeddingModelBase[Any] | None, EmbeddingTestResult]:
    """Create and call a model, including strict dimension checks."""
    timeout = config.health_check_timeout if timeout is None else timeout
    started = time.monotonic()
    actual_dimensions: int | None = None
    try:
        model = create_embedding_model(config, max_retries=1)
        response = await asyncio.wait_for(model([_TEST_TEXT]), timeout=timeout)
        if len(response.embeddings) != 1:
            raise RuntimeError(
                "Embedding service returned an unexpected result count",
            )
        embedding = response.embeddings[0]
        if not embedding:
            raise RuntimeError("Embedding service returned an empty vector")
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in embedding
        ):
            raise RuntimeError("Embedding service returned invalid numbers")

        actual_dimensions = len(embedding)
        if actual_dimensions != config.dimensions:
            raise RuntimeError(
                "Embedding dimension mismatch: "
                f"expected {config.dimensions}, got {actual_dimensions}",
            )
        latency_ms = round((time.monotonic() - started) * 1000)
        return model, EmbeddingTestResult(
            success=True,
            configured_dimensions=config.dimensions,
            actual_dimensions=actual_dimensions,
            latency_ms=latency_ms,
            message="Embedding service is available",
        )
    except Exception as exc:  # Provider SDKs expose many exception types.
        latency_ms = round((time.monotonic() - started) * 1000)
        return None, EmbeddingTestResult(
            success=False,
            configured_dimensions=config.dimensions,
            actual_dimensions=actual_dimensions,
            latency_ms=latency_ms,
            message=str(exc) or type(exc).__name__,
        )


def embedding_config_fingerprint(
    config: EmbeddingModelConfig,
) -> tuple[Any, ...]:
    """Fingerprint fields that determine the remote embedding service."""
    return (
        config.backend,
        config.api_key,
        config.base_url.strip().rstrip("/"),
        config.model_name.strip(),
        config.dimensions,
        config.use_dimensions,
    )


def embedding_vector_space_fingerprint(
    config: EmbeddingModelConfig,
) -> tuple[Any, ...]:
    """Return fields whose changes make existing vectors incompatible."""
    return (
        config.backend,
        config.base_url.strip().rstrip("/"),
        config.model_name.strip(),
        config.dimensions,
        config.use_dimensions,
    )
