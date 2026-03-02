# -*- coding: utf-8 -*-
"""Normalize query exceptions into user-actionable runtime errors."""
from __future__ import annotations

import asyncio
from collections.abc import Iterator

_TIMEOUT_MESSAGE_HINTS = (
    "timeout",
    "timed out",
    "request timed out",
)
_NETWORK_TIMEOUT_MODULE_PREFIXES = (
    "openai",
    "httpx",
    "httpcore",
    "anyio",
)


class AgentQueryError(RuntimeError):
    """Base runtime error type for query execution failures."""


class AgentModelTimeoutError(AgentQueryError):
    """Raised when the upstream model provider request timed out."""


def _iter_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield exception and causal chain without infinite loops."""
    seen: set[int] = set()
    current: BaseException | None = exc

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        if current.__cause__ is not None:
            current = current.__cause__
        elif (
            current.__context__ is not None
            and not current.__suppress_context__
        ):
            current = current.__context__
        else:
            current = None


def _is_timeout_like(exc: BaseException) -> bool:
    """Check whether an exception indicates timeout semantics."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True

    type_name = type(exc).__name__.lower()
    if "timeout" in type_name:
        return True

    message = str(exc).lower()
    return any(token in message for token in _TIMEOUT_MESSAGE_HINTS)


def is_model_timeout_error(exc: BaseException) -> bool:
    """Return True when exception chain indicates provider/network timeout."""
    chain = list(_iter_exception_chain(exc))
    has_timeout = any(_is_timeout_like(item) for item in chain)
    if not has_timeout:
        return False

    return any(
        type(item).__module__.startswith(_NETWORK_TIMEOUT_MODULE_PREFIXES)
        for item in chain
    )


def _build_timeout_error_message(exc: BaseException) -> str:
    """Build a concise and actionable timeout error message."""
    detail = str(exc).strip()
    head = (
        "Model provider request timed out. Please retry. "
        "If this keeps happening, check network stability, provider "
        "service status, and model settings (base_url/model)."
    )
    if detail:
        return f"{head} Upstream detail: {type(exc).__name__}: {detail}"
    return f"{head} Upstream detail: {type(exc).__name__}"


def map_query_exception(exc: Exception) -> Exception:
    """Map internal exceptions to user-facing runtime exceptions."""
    if is_model_timeout_error(exc):
        return AgentModelTimeoutError(_build_timeout_error_message(exc))
    return exc
