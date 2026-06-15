# -*- coding: utf-8
"""Python code execution with file-baseline-protected path approval when needed."""

from __future__ import annotations

import logging
from typing import Any

from agentscope.tool import ToolResponse
from agentscope.tool import execute_python_code as _execute_python_code_impl

logger = logging.getLogger(__name__)


def _code_preview(code: str, *, limit: int = 240) -> str:
    snippet = (code or "").replace("\n", "\\n")
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit] + "…"


async def execute_python_code(code: str, **kwargs: Any) -> ToolResponse:
    """Run Python code; require approval when code may write protected file baseline targets."""
    logger.info(
        "file_baseline_python_tool_enter wrapper=qwenpaw code_preview=%s",
        _code_preview(code),
    )
    try:
        from ...security.file_baseline_bridge import try_guarded_python_code

        guard = await try_guarded_python_code(
            code=code,
            execute_fn=lambda: _execute_python_code_impl(code, **kwargs),
        )
        logger.info(
            "file_baseline_python_tool_guard outcome status=%s handled=%s message=%s",
            guard.status,
            guard.handled,
            guard.message or "",
        )
        if guard.response is not None:
            return guard.response
    except Exception as exc:
        logger.warning(
            "file_baseline_python_tool_bypass reason=guard_exception "
            "error=%s code_preview=%s",
            exc,
            _code_preview(code),
            exc_info=True,
        )
    return await _execute_python_code_impl(code, **kwargs)
