# -*- coding: utf-8 -*-
"""Utility for bridging qwenpaw tool functions to AgentScope 2.0 Toolkit.

qwenpaw tools return ``ToolResponse``; AgentScope 2.0's ``Toolkit.call_tool``
requires ``ToolChunk`` or ``AsyncGenerator[ToolChunk]``.  This module
provides :func:`adapt_tool` which wraps a qwenpaw tool so its return value
satisfies the 2.0 contract, and :func:`make_tool` which creates either a
plain ``FunctionTool`` or a ``GuardedFunctionTool`` from the wrapper.
"""
from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def adapt_tool(func: Callable) -> Callable:
    """Wrap a qwenpaw tool so it returns ``ToolChunk`` instead of
    ``ToolResponse``.

    Idempotent — the ``__qp_tool_adapted__`` marker prevents double-wrapping.
    """
    if getattr(func, "__qp_tool_adapted__", False):
        return func

    if inspect.isasyncgenfunction(func):
        raise NotImplementedError(
            f"async-generator tools not yet supported: "
            f"{getattr(func, '__name__', func)!r}",
        )

    from agentscope.tool import ToolChunk

    @functools.wraps(func)
    async def _wrapper(**kwargs: Any) -> Any:
        tr = await func(**kwargs)
        if isinstance(tr, ToolChunk):
            return tr
        return ToolChunk(
            content=getattr(tr, "content", None),
            state=getattr(tr, "state", None),
            is_last=True,
        )

    _wrapper.__qp_tool_adapted__ = True  # type: ignore[attr-defined]
    return _wrapper


def make_tool(
    func: Callable,
    *,
    agent_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Create a ``FunctionTool`` (or ``GuardedFunctionTool``) from a qwenpaw
    tool function.

    When *agent_id* is provided, the tool is wrapped in a
    ``GuardedFunctionTool`` that routes permission checks through qwenpaw's
    tool-guard engine.
    """
    from agentscope.tool import FunctionTool

    adapted = adapt_tool(func)
    if agent_id is not None:
        from .._compat.runtime_engine import GuardedFunctionTool

        return GuardedFunctionTool(
            adapted,
            agent_id=agent_id,
            name=name,
            description=description,
        )
    return FunctionTool(adapted, name=name, description=description)
