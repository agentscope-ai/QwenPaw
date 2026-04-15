# -*- coding: utf-8 -*-
"""Optional Langfuse observability integration for LLM calls."""

from __future__ import annotations

import importlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_BOOL_TRUE = {"1", "true", "yes", "on", "y"}


@dataclass
class GenerationContext:
    """Runtime context for a single LLM generation."""

    started_at: float
    generation: Any | None


class LangfuseObserver:
    """Langfuse observer wrapper that never breaks model execution."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def from_env() -> "LangfuseObserver | None":
        """Build observer from environment variables, or return ``None``."""
        if not _is_enabled():
            return None

        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        if not public_key or not secret_key:
            logger.warning(
                "Langfuse is enabled but LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY"
                " are missing; tracing disabled.",
            )
            return None

        try:
            langfuse_module = importlib.import_module("langfuse")
        except ImportError:
            logger.warning(
                "Langfuse is enabled but package 'langfuse' is not installed; "
                "install with `pip install langfuse`.",
            )
            return None

        langfuse_cls = getattr(langfuse_module, "Langfuse", None)
        if langfuse_cls is None:
            logger.warning(
                "Langfuse package loaded but Langfuse client class missing;"
                " tracing disabled.",
            )
            return None

        kwargs: dict[str, Any] = {
            "public_key": public_key,
            "secret_key": secret_key,
        }
        host = (
            os.getenv("LANGFUSE_HOST", "").strip()
            or os.getenv("LANGFUSE_BASE_URL", "").strip()
        )
        if host:
            kwargs["host"] = host

        project = os.getenv("LANGFUSE_PROJECT", "").strip()
        if project:
            kwargs["project"] = project

        try:
            client = langfuse_cls(**kwargs)
            return LangfuseObserver(client)
        except Exception as exc:
            logger.warning("Failed to initialize Langfuse client: %s", exc)
            return None

    def start_generation(
        self,
        *,
        provider_id: str,
        model_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> GenerationContext:
        """Start a Langfuse generation and return runtime context."""
        prompt = _messages_to_prompt(messages)
        metadata = {
            "provider": provider_id,
            "tools_count": len(tools or []),
            "source": "qwenpaw",
        }
        generation = None
        try:
            trace = self._client.trace(
                id=f"qwenpaw-trace-{uuid.uuid4().hex}",
                name="qwenpaw.llm",
                input=prompt,
                metadata=metadata,
            )
            generation = trace.generation(
                id=f"qwenpaw-generation-{uuid.uuid4().hex}",
                name=f"{provider_id}.{model_name}",
                model=model_name,
                input=prompt,
                metadata=metadata,
            )
        except Exception as exc:
            logger.debug("Failed to start Langfuse generation: %s", exc)
        return GenerationContext(
            started_at=time.perf_counter(),
            generation=generation,
        )

    def finish_success(
        self,
        context: GenerationContext,
        *,
        response: Any,
        usage: Any | None,
    ) -> None:
        """Complete generation with success payload and flush."""
        if context.generation is None:
            return
        try:
            context.generation.end(
                output=_response_to_text(response),
                usage_details=_usage_to_dict(usage),
                metadata={
                    "latency_ms": round(
                        (time.perf_counter() - context.started_at) * 1000,
                        2,
                    ),
                },
            )
            self._safe_flush()
        except Exception as exc:
            logger.debug("Failed to finish Langfuse generation: %s", exc)

    def finish_error(
        self,
        context: GenerationContext,
        *,
        error: Exception,
    ) -> None:
        """Complete generation with error payload and flush."""
        if context.generation is None:
            return
        try:
            context.generation.end(
                level="ERROR",
                status_message=str(error),
                metadata={
                    "latency_ms": round(
                        (time.perf_counter() - context.started_at) * 1000,
                        2,
                    ),
                    "error_type": type(error).__name__,
                },
            )
            self._safe_flush()
        except Exception as exc:
            logger.debug("Failed to finish Langfuse error generation: %s", exc)

    def _safe_flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:
            logger.debug("Failed to flush Langfuse events: %s", exc)


_OBSERVER: LangfuseObserver | None = None
_OBSERVER_LOADED = False
_OBSERVER_LOCK = Lock()


def get_langfuse_observer() -> LangfuseObserver | None:
    """Return singleton Langfuse observer (lazy init)."""
    global _OBSERVER, _OBSERVER_LOADED  # pylint: disable=global-statement
    if _OBSERVER_LOADED:
        return _OBSERVER
    with _OBSERVER_LOCK:
        if not _OBSERVER_LOADED:
            _OBSERVER = LangfuseObserver.from_env()
            _OBSERVER_LOADED = True
    return _OBSERVER


def _is_enabled() -> bool:
    toggle = os.getenv("QWENPAW_LANGFUSE_ENABLED")
    if toggle is None:
        toggle = os.getenv("LANGFUSE_ENABLED")
    if toggle is not None:
        return toggle.strip().lower() in _BOOL_TRUE
    return bool(os.getenv("LANGFUSE_SECRET_KEY"))


def _messages_to_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prompt: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        prompt.append(
            {
                "role": item.get("role"),
                "content": item.get("content"),
                "name": item.get("name"),
            },
        )
    return prompt


def _response_to_text(response: Any) -> Any:
    if response is None:
        return None
    content = getattr(response, "content", None)
    if not isinstance(content, list):
        return content

    chunks: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                chunks.append(str(block["text"]))
            elif block.get("type") == "thinking" and block.get("thinking"):
                chunks.append(str(block["thinking"]))
    if chunks:
        return "\n".join(chunks)
    return content


def _usage_to_dict(usage: Any | None) -> dict[str, int]:
    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    prompt_tokens = _to_int(getattr(usage, "input_tokens", 0))
    completion_tokens = _to_int(getattr(usage, "output_tokens", 0))
    total_tokens = _to_int(getattr(usage, "total_tokens", 0))
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "input": prompt_tokens,
        "output": completion_tokens,
        "total": total_tokens,
    }
