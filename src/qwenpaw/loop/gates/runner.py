# -*- coding: utf-8 -*-
"""Run registered stop handlers and return result.

Decouples stop handler execution logic from the agent class.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import StopAction, StopHandlerResult

logger = logging.getLogger(__name__)


async def run_stop_handlers(
    handlers: list,
    *,
    agent: Any,
    final_msg: Any = None,
    iteration: int = 0,
) -> StopHandlerResult:
    """Execute stop handlers in priority order.

    Args:
        handlers: List of StopHandlerRegistration objects.
        agent: The agent instance (passed as ctx).
        final_msg: The agent's Msg if text, None if tools.
        iteration: Current iteration number.

    Returns:
        StopHandlerResult with STOP or CONTINUE.
    """
    if not handlers:
        return StopHandlerResult(action=StopAction.STOP)

    handlers = sorted(handlers, key=lambda h: h.priority)

    ctx = {
        "final_msg": final_msg,
        "agent": agent,
        "iteration": iteration,
        "has_tool_calls": final_msg is None,
    }

    for reg in handlers:
        try:
            result = await reg.handler(ctx)
        except Exception as exc:
            logger.warning(
                "Stop handler '%s' raised: %s",
                reg.name,
                exc,
            )
            continue

        if isinstance(result, StopHandlerResult):
            if result.action in (
                StopAction.STOP,
                StopAction.CONTINUE,
            ):
                return result
        elif isinstance(result, dict):
            action = result.get("action", "stop")
            if action == "stop":
                return StopHandlerResult(
                    action=StopAction.STOP,
                    reason=result.get("reason", ""),
                )
            if action in ("continue", "block"):
                return StopHandlerResult(
                    action=StopAction.CONTINUE,
                    continuation_message=result.get(
                        "message",
                        "",
                    ),
                    reason=result.get("reason", ""),
                )

    return StopHandlerResult(action=StopAction.STOP)


__all__ = ["run_stop_handlers"]
