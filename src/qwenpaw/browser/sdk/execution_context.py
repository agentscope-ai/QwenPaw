# -*- coding: utf-8 -*-
"""Per-execution owner and cached Browser context."""

from __future__ import annotations
import contextvars
import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .contracts import Owner

if TYPE_CHECKING:
    from .facade import Browser


@dataclass
class ExecutionContext:
    owner: Owner
    context: str = "auto"
    resolved_backend: str = ""
    automatic_identity_fallback: bool = False
    browser: Browser | None = None
    browser_connecting: asyncio.Future[Browser] | None = None


_CURRENT: contextvars.ContextVar[
    "ExecutionContext | None"
] = contextvars.ContextVar(
    "qwenpaw_browser_exec_ctx",
    default=None,
)
_PERCEPTION_COUNT: contextvars.ContextVar[int] = contextvars.ContextVar(
    "browser_perception_count",
    default=0,
)


def get_execution_context() -> "ExecutionContext | None":
    return _CURRENT.get()


def set_execution_context(ctx: "ExecutionContext | None") -> contextvars.Token:
    return _CURRENT.set(ctx)


def reset_execution_context(token: contextvars.Token) -> None:
    _CURRENT.reset(token)


def reset_perception_count() -> None:
    """Clear this execution's fact-based perception counter."""
    _PERCEPTION_COUNT.set(0)


def record_perception() -> None:
    """Record one snapshot performed by the executing SDK code."""
    _PERCEPTION_COUNT.set(_PERCEPTION_COUNT.get() + 1)


def get_perception_count() -> int:
    """Return the number of snapshots in the current execution context."""
    return _PERCEPTION_COUNT.get()
