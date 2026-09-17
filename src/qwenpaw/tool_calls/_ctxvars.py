# -*- coding: utf-8 -*-
"""ContextVar for tool-internal access to ToolCallContext."""
from __future__ import annotations

from contextvars import ContextVar

from ._context import ToolCallContext

_current: ContextVar[ToolCallContext | None] = ContextVar(
    "current_tool_call_context",
    default=None,
)


def set_call_context(ctx: ToolCallContext) -> object:
    return _current.set(ctx)


def reset_call_context(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def get_call_context() -> ToolCallContext | None:
    return _current.get()
