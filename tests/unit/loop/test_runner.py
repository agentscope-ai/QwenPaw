# -*- coding: utf-8 -*-
"""Tests for stop-handler result application."""
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.handler import StopHandler
from qwenpaw.loop.gates.runner import apply_stop_result, check_pending_gates
from qwenpaw.modes.goal.gates import GoalTurnGate
from qwenpaw.modes.goal.goal_mode import GoalSession


def _goal_handler(session: GoalSession) -> StopHandler:
    """Build an active goal handler for continuation tests."""
    mode: Any = SimpleNamespace(session_by_ctx_var=lambda: session)
    handler = StopHandler()
    handler.register(GoalTurnGate(mode))
    return handler


@pytest.mark.asyncio
async def test_goal_tool_call_does_not_defer_continuation() -> None:
    """Tool calls continue naturally without an injected user prompt."""
    agent = SimpleNamespace(_gate_pending_stop=None)
    session = GoalSession(goal=f"Ship the feature")
    handler = _goal_handler(session)
    for _ in range(session.max_iterations + 1):
        result = await handler({"has_tool_calls": True})
        apply_stop_result(agent, result, is_tool_call=True)

        assert check_pending_gates(agent) is None
    assert session.iteration == 0
    assert session.active
    assert vars(agent) == {"_gate_pending_stop": None}

    session.active = False
    result = await handler({"has_tool_calls": True})
    apply_stop_result(agent, result, is_tool_call=True)
    assert check_pending_gates(agent) is result


@pytest.mark.asyncio
async def test_goal_text_exit_keeps_continuation_prompt() -> None:
    """A text-only exit still receives the active goal continuation."""
    session = GoalSession(goal=f"Ship the feature")
    handler = _goal_handler(session)
    for turn in range(1, session.max_iterations):
        result = await handler({"has_tool_calls": False})
        assert session.iteration == turn
        assert result.action == StopAction.INTERRUPT_AND_CONTINUE
        assert result.continuation_message.startswith(
            "Continue working toward the active goal.",
        )

    result = await handler({"has_tool_calls": False})
    assert result.action == StopAction.TERMINATE
    assert session.iteration == session.max_iterations
    assert not session.active


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
