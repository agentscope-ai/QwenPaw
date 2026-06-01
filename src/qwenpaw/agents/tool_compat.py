# -*- coding: utf-8 -*-
"""Tool construction helpers for agentscope 2.0 Toolkit.

:func:`make_tool` creates either a plain ``FunctionTool`` or a
``GuardedFunctionTool`` (with tool-guard permission checks) from a
qwenpaw tool function.
"""
from __future__ import annotations

from typing import Any, Callable


def make_tool(
    func: Callable,
    *,
    agent_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Create a ``FunctionTool`` or ``GuardedFunctionTool``.

    When *agent_id* is provided, the tool gets permission checks
    via qwenpaw's tool-guard engine.
    """
    from agentscope.tool import FunctionTool

    if agent_id is not None:
        from ..runtime_engine import GuardedFunctionTool

        return GuardedFunctionTool(
            func,
            agent_id=agent_id,
            name=name,
            description=description,
        )
    return FunctionTool(func, name=name, description=description)
