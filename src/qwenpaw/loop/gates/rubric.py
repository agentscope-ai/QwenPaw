# -*- coding: utf-8 -*-
"""Rubric evaluation strategies for loop completion.

Architecture:
    RubricStrategy (ABC)
    ├── DefaultRubric     — always SATISFIED (no rubric)
    ├── GoalStatusRubric  — checks session.active
    └── SubAgentRubric    — placeholder for subagent eval
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


class RubricVerdict(str, Enum):
    """Grader verdicts."""

    SATISFIED = "satisfied"
    NEEDS_REVISION = "needs_revision"
    FAILED = "failed"
    GRADER_ERROR = "grader_error"
    MAX_ITERATIONS = "max_iterations_reached"


@dataclass
class RubricEvaluation:
    """Result of one rubric evaluation pass."""

    iteration: int
    verdict: RubricVerdict
    explanation: str = ""
    feedback: str = ""


# ---- Abstract Strategy ----


class RubricStrategy(ABC):
    """Base class for rubric evaluation strategies."""

    @abstractmethod
    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        """Evaluate whether the goal is met."""


# ---- Concrete Strategies ----


class DefaultRubric(RubricStrategy):
    """No rubric — always SATISFIED.

    Used for loops that have no rubric requirement.
    The loop terminates normally after each turn.
    """

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.SATISFIED,
            explanation="No rubric registered",
        )


class GoalStatusRubric(RubricStrategy):
    """Hardcoded status check for GoalMode.

    Accepts a ``get_session_fn`` callback that retrieves
    the current GoalSession via ContextVar (no scan).
    Returns SATISFIED when session.active is False
    (set by update_goal tool), NEEDS_REVISION otherwise.
    """

    def __init__(
        self,
        get_session_fn: Callable[[], Optional[Any]],
    ) -> None:
        self._get_session = get_session_fn

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        session = self._get_session()
        if session is None or not session.active:
            return RubricEvaluation(
                iteration=iteration,
                verdict=RubricVerdict.SATISFIED,
                explanation=("Goal completed via update_goal"),
            )
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.NEEDS_REVISION,
            explanation="Goal still active",
        )


class SubAgentRubric(RubricStrategy):
    """Placeholder for subagent-based verification.

    Concrete implementation should follow the
    oh-my-claudecode/ralph pattern: spawn a subagent
    to verify, then check state file key-values for
    the verdict (not LLM output parsing).

    TODO: implement file-based state verification.
    """

    def __init__(
        self,
        spawn_fn: Any = None,
        fork: bool = False,
    ) -> None:
        self._spawn_fn = spawn_fn
        self._fork = fork

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        """Placeholder — returns GRADER_ERROR."""
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.GRADER_ERROR,
            explanation=("SubAgentRubric not yet implemented"),
        )


class StandaloneRubricGate(StopGate):
    """Re-prompt on text-only responses.

    Prevents premature stop when the LLM outputs text
    without any tool calls.  Counts interventions per
    request cycle; stops re-prompting after
    ``max_interventions``.
    """

    def __init__(
        self,
        prompt: str = "",
        max_interventions: int = 1,
    ) -> None:
        self._prompt = prompt
        self._max = max_interventions
        self._count = 0

    @property
    def name(self) -> str:
        return "standalone_rubric"

    @property
    def priority(self) -> int:
        return 90

    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Return CONTINUE up to max_interventions.

        Only triggers on text-only responses
        (no tool calls).
        """
        if isinstance(ctx, dict) and ctx.get(
            "has_tool_calls",
        ):
            return None

        if self._count >= self._max:
            self._count = 0
            return None

        self._count += 1
        logger.debug(
            "StandaloneRubricGate: intervene %d/%d",
            self._count,
            self._max,
        )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self._prompt,
            reason="text-only response re-prompt",
        )


__all__ = [
    "StandaloneRubricGate",
    "DefaultRubric",
    "GoalStatusRubric",
    "RubricEvaluation",
    "RubricStrategy",
    "RubricVerdict",
    "SubAgentRubric",
]
