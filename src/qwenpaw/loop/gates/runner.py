# -*- coding: utf-8 -*-
"""Run registered stop handlers and return result.

Decouples stop handler execution logic from the agent class.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import StopAction, StopHandlerResult

logger = logging.getLogger(__name__)


def _filter_by_scope(
    handlers: list,
) -> list:
    """Keep only the active scope's handlers.

    If any handler with a non-"default" scope has at
    least one active gate, only that scope's handlers
    run; "default"-scoped handlers are skipped.
    Handlers without a scope (``scope=""``) always run.
    """
    from .loop_gate import LoopGate

    active_scope: str = ""
    for reg in handlers:
        scope = getattr(reg, "scope", "")
        if scope and scope != "default":
            handler = reg.handler
            gates = getattr(handler, "gates", [])
            for g in gates:
                # pylint: disable=protected-access
                has_state = isinstance(g, LoopGate) and g._state() is not None
                if has_state:
                    active_scope = scope
                    break
            if active_scope:
                break

    result: list = []
    for reg in handlers:
        scope = getattr(reg, "scope", "")
        if not scope:
            result.append(reg)
        elif active_scope and scope == active_scope:
            result.append(reg)
        elif not active_scope and scope == "default":
            result.append(reg)
        else:
            logger.debug(
                "Skipping handler '%s' scope=%s active=%s",
                reg.name,
                scope,
                active_scope or "(none)",
            )
    return result


async def run_stop_handlers(
    handlers: list,
    *,
    agent: Any,
    final_msg: Any = None,
    iteration: int = 0,
) -> StopHandlerResult:
    """Execute stop handlers in priority order.

    Handlers are first filtered by scope so that
    mode-specific handlers take precedence over
    default ones.

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

    handlers = _filter_by_scope(handlers)
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


def apply_stop_result(  # pylint: disable=protected-access
    agent: Any,
    stop_result: StopHandlerResult,
    *,
    is_tool_call: bool,
) -> None:
    """Process stop_result and set pending state on agent.

    Called after _run_stop_handlers in a tool-call iteration.
    Defers both STOP and CONTINUE actions to next iteration.
    """
    if is_tool_call:
        if stop_result.action == StopAction.STOP and stop_result.reason:
            logger.info(
                "Gate wants stop (deferred): %s",
                stop_result.reason,
            )
            agent._gate_pending_stop = stop_result


def check_pending_gates(  # pylint: disable=protected-access
    agent: Any,
) -> StopHandlerResult | None:
    """Check and consume pending gate state.

    Returns:
        StopHandlerResult if a pending STOP should be applied,
        None otherwise (also injects pending continue into ctx).
    """
    pending = getattr(agent, "_gate_pending_stop", None)
    if pending is not None:
        agent._gate_pending_stop = None
        logger.info(
            "Gate pending stop applied: %s",
            pending.reason,
        )
        return pending

    cont_msg = getattr(
        agent,
        "_gate_pending_continue",
        None,
    )
    if cont_msg:
        agent._gate_pending_continue = None
        from agentscope.message import Msg, TextBlock

        from ...constant import QWENPAW_MESSAGE_TAG_KEY

        agent.state.context.append(
            Msg(
                name="user",
                role="user",
                content=[
                    TextBlock(type="text", text=cont_msg),
                ],
                metadata={
                    QWENPAW_MESSAGE_TAG_KEY: ("loop_continuation"),
                },
            ),
        )
    return None


__all__ = [
    "run_stop_handlers",
    "apply_stop_result",
    "check_pending_gates",
]
