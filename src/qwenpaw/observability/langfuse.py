# -*- coding: utf-8 -*-
"""Langfuse trace context for QwenPaw agent turns.

This module is intentionally optional: QwenPaw does not depend on langfuse at
install time, so every helper becomes a no-op when Langfuse is unavailable.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LangfuseTraceContext:
    trace_id: str
    parent_observation_id: str | None
    name: str
    metadata: dict[str, Any]


_current_trace: ContextVar[LangfuseTraceContext | None] = ContextVar(
    "qwenpaw_langfuse_trace",
    default=None,
)


def _langfuse_available() -> bool:
    return importlib.util.find_spec("langfuse") is not None


def is_langfuse_enabled() -> bool:
    """Return True when the Langfuse OpenAI instrumentation can be used."""

    if not os.environ.get("LANGFUSE_SECRET_KEY") or not _langfuse_available():
        return False
    try:
        importlib.import_module("langfuse.openai")
    except Exception:
        logger.debug(
            "Failed to register Langfuse OpenAI tracing",
            exc_info=True,
        )
        return False
    return True


def _langfuse_client() -> Any | None:
    if not _langfuse_available():
        return None
    try:
        from langfuse import get_client  # type: ignore[import]

        return get_client()
    except Exception:
        logger.debug("Failed to initialize Langfuse client", exc_info=True)
        return None


def set_current_trace(
    *,
    trace_id: str,
    parent_observation_id: str | None,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    _current_trace.set(
        LangfuseTraceContext(
            trace_id=trace_id,
            parent_observation_id=parent_observation_id,
            name=name,
            metadata=dict(metadata or {}),
        ),
    )


def clear_current_trace() -> None:
    _current_trace.set(None)


def get_current_trace() -> LangfuseTraceContext | None:
    return _current_trace.get()


def current_generation_kwargs(model_name: str | None = None) -> dict[str, Any]:
    """Build Langfuse-only kwargs for the OpenAI SDK wrapper."""

    ctx = get_current_trace()
    if ctx is None:
        return {}

    metadata = {
        **ctx.metadata,
        "langfuse_observation_kind": "llm",
    }
    name = f"llm.{model_name}" if model_name else "llm"
    kwargs: dict[str, Any] = {
        "trace_id": ctx.trace_id,
        "name": name,
        "metadata": metadata,
    }
    if ctx.parent_observation_id:
        kwargs["parent_observation_id"] = ctx.parent_observation_id
    return kwargs


@asynccontextmanager
async def agent_trace_scope(
    *,
    trace_id: str,
    name: str,
    metadata: dict[str, Any],
    input: Any | None = None,  # pylint: disable=redefined-builtin
    client_factory: Callable[[], Any | None] | None = None,
) -> AsyncIterator[Any | None]:
    """Create the root Langfuse span for one agent ReAct loop."""

    previous = get_current_trace()
    if client_factory is None and not is_langfuse_enabled():
        yield None
        return

    client = (client_factory or _langfuse_client)()
    root = None
    parent_observation_id: str | None = None

    try:
        if client is not None:
            root = client.start_observation(
                as_type="span",
                name=name,
                input=input,
                metadata=metadata,
                trace_context={"trace_id": trace_id},
            )
            parent_observation_id = str(getattr(root, "id", "") or "") or None

        set_current_trace(
            trace_id=trace_id,
            parent_observation_id=parent_observation_id,
            name=name,
            metadata=metadata,
        )
        yield root
        if root is not None:
            root.update(output={"status": "success"})
    except Exception as exc:
        if root is not None:
            root.update(
                level="ERROR",
                status_message=str(exc),
                output={"status": "error"},
            )
        raise
    finally:
        if root is not None:
            root.end()
        if previous is None:
            clear_current_trace()
        else:
            set_current_trace(
                trace_id=previous.trace_id,
                parent_observation_id=previous.parent_observation_id,
                name=previous.name,
                metadata=previous.metadata,
            )


@asynccontextmanager
async def tool_span(
    *,
    name: str,
    input: Any | None = None,  # pylint: disable=redefined-builtin
    metadata: dict[str, Any] | None = None,
    client_factory: Callable[[], Any | None] | None = None,
) -> AsyncIterator[Any | None]:
    """Create a Langfuse tool observation under the current agent trace."""

    ctx = get_current_trace()
    if client_factory is None and not is_langfuse_enabled():
        yield None
        return

    client = (
        (client_factory or _langfuse_client)() if ctx is not None else None
    )
    observation = None

    try:
        if client is not None and ctx is not None:
            trace_context: dict[str, str] = {"trace_id": ctx.trace_id}
            if ctx.parent_observation_id:
                trace_context["parent_span_id"] = ctx.parent_observation_id
            observation = client.start_observation(
                as_type="tool",
                name=f"tool.{name}",
                input=input,
                metadata={
                    **ctx.metadata,
                    **(metadata or {}),
                    "langfuse_observation_kind": "tool",
                    "tool_name": name,
                },
                trace_context=trace_context,
            )
        yield observation
    except Exception as exc:
        if observation is not None:
            observation.update(
                level="ERROR",
                status_message=str(exc),
                output={"status": "error"},
            )
        raise
    finally:
        if observation is not None:
            observation.end()
