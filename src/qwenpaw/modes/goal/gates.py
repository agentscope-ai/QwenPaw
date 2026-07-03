# -*- coding: utf-8 -*-
"""Goal-mode stop gates.

Separated from goal_mode.py for maintainability.

GoalTurnGate tracks cross-request goal turns (outer
loop), distinct from IterationGate which tracks
per-request ReAct iterations (inner loop).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

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
DEFAULT_MAX_TOKENS = 300000


def _update_goal_tokens(
    session: Any,
    ctx: Any,
) -> None:
    """Accumulate token usage from model wrapper."""
    try:
        from ...token_usage.model_wrapper import (
            TokenRecordingModelWrapper,
        )

        agent = ctx.get("agent") if isinstance(ctx, dict) else None
        if agent is None:
            return
        rc = getattr(agent, "_request_context", {})
        sid = rc.get("session_id", "")
        if not sid:
            return
        store = getattr(
            TokenRecordingModelWrapper,
            "_usage_by_session",
            {},
        )
        usage = store.get(sid)
        if usage:
            session.tokens_used = usage.get(
                "total_tokens",
                session.tokens_used,
            )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to update goal tokens",
            exc_info=True,
        )


class GoalTurnGate(LoopGate):
    """Goal-mode turn gate (outer loop).

    Tracks cross-request goal turns via GoalSession.
    NOT the same as IterationGate which tracks
    per-request ReAct iterations (inner loop).

    Returns:
        CONTINUE — session active, under limit.
        STOP — session deactivated (update_goal
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
    ) -> Optional[StopHandlerResult]:
        """Check turn limit via GoalSession."""
        session = self._mode.session_by_ctx_var()
        if session is None:
            return None

        if not session.active:
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=(f"Goal completed: " f"{session.last_verdict}"),
            )

        session.iteration += 1
        _update_goal_tokens(session, ctx)
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
                action=StopAction.STOP,
                reason="Max iterations reached",
            )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
        )


class GoalBudgetGate(LoopGate):
    """Goal-mode token budget gate.

    Returns STOP when token budget is exceeded.
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
    ) -> Optional[StopHandlerResult]:
        session = self._mode.session_by_ctx_var()
        if session is None or not session.active:
            return None
        if session.tokens_used < session.max_tokens:
            return None

        session.active = False
        return StopHandlerResult(
            action=StopAction.STOP,
            reason="Token budget exceeded",
        )


class RubricGate(LoopGate):
    """Rubric evaluation gate (session-safe).

    SATISFIED (goal completed) -> STOP.
    Otherwise -> None (no objection, continue).
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
    ) -> Optional[StopHandlerResult]:
        """Evaluate rubric for goal completion."""
        session = self._mode.session_by_ctx_var()
        if session is None:
            return None

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
                action=StopAction.STOP,
                reason=evaluation.explanation,
            )
        return None


__all__ = [
    "GoalBudgetGate",
    "GoalTurnGate",
    "RubricGate",
]
