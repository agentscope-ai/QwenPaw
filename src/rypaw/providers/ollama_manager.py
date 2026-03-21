# -*- coding: utf-8 -*-
"""Ollama model management using the Ollama Python SDK.

This module mirrors the structure of local_models.manager, but delegates all
lifecycle operations to the running Ollama daemon instead of managing files
or a manifest.json. Ollama remains the single source of truth for its models.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator
from ..constant import MODEL_PROVIDER_CHECK_TIMEOUT

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
            "The 'ollama' Python package is required. You may have "
            "installed Ollama via their CLI or desktop app, but you "
            "also need the Python SDK to manage models from CoPaw. "
            "Please install it with: pip install 'copaw[ollama]'",
        ) from e
    return ollama


def _base_url_to_host(base_url: str) -> Optional[str]:
    """Convert an OpenAI-compat ``base_url`` (with ``/v1``) to an Ollama host.

    The providers.json stores ``http://host:port/v1`` for OpenAI compatibility,
    but the native Ollama SDK expects ``http://host:port``.
    """
    if not base_url:
        return None
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url or None


class OllamaModelManager:
    """High-level wrapper around the Ollama SDK for model lifecycle.

    All operations delegate to the Ollama daemon; this module does not manage
    files or persist a manifest. It is safe to call these methods from
    background tasks and CLIs.

    Every method accepts an optional *host* parameter (e.g.
    ``http://remote:11434``) that overrides the SDK default.
    """

    @staticmethod
    def _make_client(host: Optional[str] = None):
        """Create an Ollama SDK client, optionally targeting a custom host."""
        ollama = _ensure_ollama()
        kwargs: dict = {"timeout": MODEL_PROVIDER_CHECK_TIMEOUT}
        if host:
            kwargs["host"] = host
        return ollama.Client(**kwargs)

    @staticmethod
    def list_models(host: Optional[str] = None) -> List[OllamaModelInfo]:
        """Return the current model list from ``ollama.list()``."""

        raw = OllamaModelManager._make_client(host).list()
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
    def pull_model(
        name: str,
        host: Optional[str] = None,
    ) -> OllamaModelInfo:
        """Pull/download a model via ``ollama.pull``.

        This call is blocking and intended to be run in a thread executor when
        used from async FastAPI endpoints.
        """

        logger.info("Pulling Ollama model: %s", name)
        OllamaModelManager._make_client(host).pull(name)
        logger.info("Pull completed: %s", name)

        for model in OllamaModelManager.list_models(host=host):
            if model.name == name:
                return model

        raise ValueError(f"Ollama model '{name}' not found after pull.")

    @staticmethod
    def delete_model(name: str, host: Optional[str] = None) -> None:
        """Delete a model from the local Ollama instance."""

        logger.info("Deleting Ollama model: %s", name)
        OllamaModelManager._make_client(host).delete(name)
        logger.info("Ollama model deleted: %s", name)
