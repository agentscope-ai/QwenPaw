# -*- coding: utf-8 -*-
"""Ollama model management using the Ollama Python SDK.

This module mirrors the structure of local_models.manager, but delegates all
lifecycle operations to the running Ollama daemon instead of managing files
or a manifest.json. Ollama remains the single source of truth for its models.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class OllamaModelInfo(BaseModel):
    """Metadata for a single Ollama model returned by ``ollama.list()``."""

    name: str = Field(..., description="Model name, e.g. 'llama3:8b'")
    size: int = Field(0, description="Approximate size in bytes (if provided)")
    digest: Optional[str] = Field(default=None, description="Model digest/id")
    modified_at: Optional[str] = Field(
        default=None,
        description="Last modified time string (from Ollama, if present)",
    )

    @field_validator("modified_at", mode="before")
    @classmethod
    def convert_datetime_to_str(
        cls,
        v: Union[str, datetime, None],
    ) -> Optional[str]:
        """Convert datetime objects to ISO format strings."""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)


def _ensure_ollama():
    """Import the ollama SDK with a helpful error message on failure."""

    try:
        import ollama  # type: ignore[import]
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "The 'ollama' Python package is required for Ollama management. "
            "Install it with: pip install 'copaw[ollama]'",
        ) from e
    return ollama


_ALLOWED_OLLAMA_SCHEMES = {"http", "https"}


def _normalize_ollama_host(host: Optional[str]) -> Optional[str]:
    """Normalize OpenAI-compatible base URL to Ollama host URL.

    Validates that the URL uses http/https to prevent SSRF attacks.
    """
    value = (host or "").strip()
    if not value:
        return None

    value = value.rstrip("/")
    # Users may configure ollama via OpenAI-compatible /v1 endpoint.
    if value.endswith("/v1"):
        value = value[:-3]
    value = value.rstrip("/")
    if not value:
        return None

    parsed = urlsplit(value)
    # SSRF protection: only allow http and https schemes
    if parsed.scheme and parsed.scheme not in _ALLOWED_OLLAMA_SCHEMES:
        logger.warning(
            "Rejecting Ollama host with unsupported scheme: %s",
            parsed.scheme,
        )
        return None
    if parsed.scheme and parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value


def _get_ollama_client(host: Optional[str] = None):
    """Return an Ollama client bound to the configured host."""
    ollama = _ensure_ollama()
    normalized = _normalize_ollama_host(host)
    if normalized:
        return ollama.Client(host=normalized)
    return ollama.Client()


class OllamaModelManager:
    """High-level wrapper around the Ollama SDK for model lifecycle.

    All operations delegate to the Ollama daemon; this module does not manage
    files or persist a manifest. It is safe to call these methods from
    background tasks and CLIs.
    """

    @staticmethod
    def list_models(host: Optional[str] = None) -> List[OllamaModelInfo]:
        """Return the current model list from ``ollama.list()``."""

        client = _get_ollama_client(host)
        raw = client.list()
        models: List[OllamaModelInfo] = []
        for m in raw.get("models", []):
            models.append(
                OllamaModelInfo(
                    name=m.get("model", ""),
                    size=m.get("size", 0) or 0,
                    digest=m.get("digest"),
                    modified_at=m.get("modified_at"),
                ),
            )
        return models

    @staticmethod
    def pull_model(name: str, host: Optional[str] = None) -> OllamaModelInfo:
        """Pull/download a model via ``ollama.pull``.

        This call is blocking and intended to be run in a thread executor when
        used from async FastAPI endpoints.
        """

        client = _get_ollama_client(host)
        logger.info("Pulling Ollama model: %s", name)
        client.pull(name)
        logger.info("Pull completed: %s", name)

        for model in OllamaModelManager.list_models(host=host):
            if model.name == name:
                return model

        raise ValueError(f"Ollama model '{name}' not found after pull.")

    @staticmethod
    def delete_model(name: str, host: Optional[str] = None) -> None:
        """Delete a model from the local Ollama instance."""

        client = _get_ollama_client(host)
        logger.info("Deleting Ollama model: %s", name)
        client.delete(name)
        logger.info("Ollama model deleted: %s", name)
