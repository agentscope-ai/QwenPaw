# -*- coding: utf-8 -*-
"""Goal-mode stop gates.

Separated from goal_mode.py for maintainability.

GoalTurnGate counts text-only exit attempts across requests. Tool-call
iterations do not consume the goal turn limit.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...loop.gates.base import (
    StopAction,
    StopHandlerResult,
)
from ...loop.gates.loop_gate import LoopGate
from ...loop.gates.rubric import RubricVerdict

if TYPE_CHECKING:
    from .goal_mode import GoalMode

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 20


class GoalTurnGate(LoopGate):
    """Goal-mode turn gate (outer loop).

    Counts text-only exit attempts via GoalSession. Tool-call iterations
    continue naturally without consuming the goal turn limit.

    Returns:
        INTERRUPT_AND_CONTINUE — active, under limit.
        TERMINATE — session deactivated (update_goal
            called) or iteration limit reached.
        None — no active session (not in goal mode).
    """

    def __init__(
        self,
        goal_mode: "GoalMode",
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        super().__init__()
        self._mode = goal_mode
        self._max_iterations = max_iterations

    @property
    def name(self) -> str:
        return "goal-turn"

    @property
    def priority(self) -> int:
        return 10

    async def check(
        self,
        ctx: Any,
    ) -> StopHandlerResult:
        """Check turn limit via GoalSession."""
        session = self._mode.session_by_ctx_var()
        if session is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        if not session.active:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=(f"Goal completed: " f"{session.last_verdict}"),
            )

        if ctx.get("has_tool_calls", False):
            return StopHandlerResult(action=StopAction.BYPASS)

        session.iteration += 1
        logger.debug(
            "GoalTurn: iter=%d/%d tokens=%d/%d",
            session.iteration,
            self._max_iterations,
            session.tokens_used,
            session.max_tokens,
        )

        if session.iteration >= self._max_iterations:
            session.active = False
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Max iterations reached",
            )
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
        )

    def build_continuation(self) -> str:
        """Build goal continuation prompt."""
        from .prompts import CONTINUATION_PROMPT

        session = self._mode.session_by_ctx_var()
        if session is None:
            return ""
        remaining = session.remaining_tokens
        return CONTINUATION_PROMPT.format(
            objective=session.goal,
            iteration=session.iteration,
            max_iterations=session.max_iterations,
            tokens_used=session.tokens_used,
            token_budget=session.token_budget_display,
            remaining_tokens=remaining
            if remaining is not None
            else f"unlimited",
        )


class GoalBudgetGate(LoopGate):
    """Goal-mode token budget gate.

    Returns TERMINATE when token budget is exceeded.
    """

    def __init__(
        self,
        goal_mode: "GoalMode",
    ) -> None:
        super().__init__()
        self._mode = goal_mode

    @property
    def name(self) -> str:
        return "goal-budget"

    @property
    def priority(self) -> int:
        return 20

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> StopHandlerResult:
        _bypass = StopHandlerResult(
            action=StopAction.BYPASS,
        )
        session = self._mode.session_by_ctx_var()
        if session is None or not session.active:
            return _bypass
        if session.max_tokens <= 0 or session.tokens_used < session.max_tokens:
            return _bypass

        session.active = False
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            reason="Token budget exceeded",
        )


class RubricGate(LoopGate):
    """Rubric evaluation gate (session-safe).

    SATISFIED (goal completed) -> TERMINATE.
    Otherwise -> BYPASS (no objection).
    """

    @property
    def name(self) -> str:
        return "goal-rubric"

    @property
    def priority(self) -> int:
        return 30

    def __init__(
        self,
        goal_mode: "GoalMode",
        rubric: Any,
    ) -> None:
        super().__init__()
        self._mode = goal_mode
        self._rubric = rubric

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> StopHandlerResult:
        """Evaluate rubric for goal completion."""
        session = self._mode.session_by_ctx_var()
        if session is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        evaluation = await self._rubric.evaluate(
            goal=session.goal,
            agent_output="",
            iteration=session.iteration,
        )
        session.last_verdict = str(
            evaluation.verdict,
        )
        logger.debug(
            "Goal rubric verdict=%s",
            evaluation.verdict,
        )

        if evaluation.verdict == RubricVerdict.SATISFIED:
            logger.info(
                "Goal completed at iter=%d",
                session.iteration,
            )
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=evaluation.explanation,
            )
        return StopHandlerResult(
            action=StopAction.BYPASS,
        )


__all__ = [
    "GoalBudgetGate",
    "GoalTurnGate",
    "RubricGate",
]
