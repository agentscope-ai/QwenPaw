# -*- coding: utf-8
"""Python code execution with persona-protected path approval when needed."""

from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse
from agentscope.tool import execute_python_code as _execute_python_code_impl


async def execute_python_code(code: str, **kwargs: Any) -> ToolResponse:
    """Run Python code; require approval when code may write protected persona files."""
    try:
        from ...security.persona_baseline_bridge import try_guarded_python_code

        guard = await try_guarded_python_code(
            code=code,
            execute_fn=lambda: _execute_python_code_impl(code, **kwargs),
        )
        if guard.handled and guard.response is not None:
            return guard.response
    except Exception:
        pass
    return await _execute_python_code_impl(code, **kwargs)
