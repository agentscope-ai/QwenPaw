# -*- coding: utf-8 -*-
"""Tests for stop-handler result application."""
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.handler import StopHandler
from qwenpaw.loop.gates.runner import apply_stop_result, check_pending_gates
from qwenpaw.modes.goal.gates import GoalTurnGate


def _goal_handler() -> StopHandler:
    """Build an active goal handler for continuation tests."""
    session = SimpleNamespace(
        active=True,
        goal="Ship the feature",
        iteration=0,
        last_verdict="",
        max_iterations=20,
        max_tokens=300000,
        tokens_used=0,
    )
    mode: Any = SimpleNamespace(session_by_ctx_var=lambda: session)
    handler = StopHandler()
    handler.register(GoalTurnGate(mode))
    return handler


@pytest.mark.asyncio
async def test_goal_tool_call_does_not_defer_continuation() -> None:
    """Tool calls continue naturally without an injected user prompt."""
    agent = SimpleNamespace(_gate_pending_stop=None)
    result = await _goal_handler()({"has_tool_calls": True})

    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message.startswith(
        "Continue working toward the active goal.",
    )

    apply_stop_result(agent, result, is_tool_call=True)

    assert vars(agent) == {"_gate_pending_stop": None}
    assert check_pending_gates(agent) is None


@pytest.mark.asyncio
async def test_goal_text_exit_keeps_continuation_prompt() -> None:
    """A text-only exit still receives the active goal continuation."""
    result = await _goal_handler()({"has_tool_calls": False})

    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.continuation_message.startswith(
        "Continue working toward the active goal.",
    )


def test_tool_call_defers_termination() -> None:
    """A terminating decision waits until tool results are processed."""
    agent = SimpleNamespace(_gate_pending_stop=None)
    result = StopHandlerResult(
        action=StopAction.TERMINATE,
        reason="Goal iteration limit reached",
    )

    apply_stop_result(agent, result, is_tool_call=True)

    assert check_pending_gates(agent) is result
    assert vars(agent)["_gate_pending_stop"] is None
