# -*- coding: utf-8 -*-
"""Rubric evaluation strategies for loop completion.

Architecture:
    RubricStrategy (ABC)
    ├── DefaultRubric     — always SATISFIED (no rubric)
    ├── GoalStatusRubric  — checks session.active
    └── SubAgentRubric    — LLM-as-Judge via subagent
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..modes.goal.goal_mode import GoalMode

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

    Returns SATISFIED only when the session has been
    explicitly deactivated (via update_goal tool).
    Otherwise returns NEEDS_REVISION to keep the
    loop running.
    """

    def __init__(self, owner: GoalMode) -> None:
        self._owner = owner

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        session = self._owner.first_active_session()
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


GRADER_SYSTEM_PROMPT = (
    "You are a strict rubric grader. "
    "Evaluate whether the agent's work satisfies "
    "the given goal. "
    "Reply with ONLY a JSON object:\n"
    '{"verdict": "satisfied" | "needs_revision",'
    ' "explanation": "...", "feedback": "..."}\n'
    "- verdict: satisfied if goal is met, "
    "needs_revision otherwise.\n"
    "- explanation: brief summary of evaluation.\n"
    "- feedback: actionable next steps if "
    "needs_revision."
)


class SubAgentRubric(RubricStrategy):
    """LLM-as-Judge via spawn_subagent.

    Expects a JSON response from the grader subagent.
    If JSON parsing fails, returns GRADER_ERROR
    (no keyword fallback).
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
        """Run rubric grading via spawn_subagent."""
        spawn_fn = self._spawn_fn
        if spawn_fn is None:
            try:
                from ..agents.tools.agent_management import (
                    spawn_subagent,
                )

                spawn_fn = spawn_subagent
            except ImportError:
                return RubricEvaluation(
                    iteration=iteration,
                    verdict=RubricVerdict.GRADER_ERROR,
                    explanation=("spawn_subagent unavailable"),
                )

        grader_task = (
            f"{GRADER_SYSTEM_PROMPT}\n\n"
            f"## Goal\n{goal}\n\n"
            f"## Agent Output (last 2000 chars)\n"
            f"{agent_output[-2000:]}\n\n"
            f"## Grading Iteration\n{iteration}"
        )

        try:
            result = await spawn_fn(
                task=grader_task,
                fork=self._fork,
                background=False,
                timeout=60,
            )
            return _parse_json_result(
                result,
                iteration,
            )
        except Exception as exc:
            logger.warning(
                "Rubric grader error: %s",
                exc,
            )
            return RubricEvaluation(
                iteration=iteration,
                verdict=RubricVerdict.GRADER_ERROR,
                explanation=f"Grader exception: {exc}",
            )


# ---- Internal helpers ----


def _extract_text(result: Any) -> str:
    """Extract plain text from subagent result."""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _parse_json_result(
    result: Any,
    iteration: int,
) -> RubricEvaluation:
    """Parse grader response — JSON only.

    If JSON parsing fails, returns GRADER_ERROR
    instead of guessing via keyword detection.
    """
    text = _extract_text(result)

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        verdict_str = data.get("verdict", "")
        if verdict_str:
            try:
                verdict = RubricVerdict(verdict_str)
            except ValueError:
                verdict = None
            if verdict is not None:
                return RubricEvaluation(
                    iteration=iteration,
                    verdict=verdict,
                    explanation=data.get(
                        "explanation",
                        "",
                    ),
                    feedback=data.get(
                        "feedback",
                        "",
                    ),
                )
    except (ValueError, json.JSONDecodeError):
        pass

    msg = f"Rubric: JSON parse failed: {text[:200]}"
    logger.warning(msg)
    return RubricEvaluation(
        iteration=iteration,
        verdict=RubricVerdict.GRADER_ERROR,
        explanation=f"Cannot parse JSON: {text[:300]}",
    )


__all__ = [
    "DefaultRubric",
    "GRADER_SYSTEM_PROMPT",
    "GoalStatusRubric",
    "RubricEvaluation",
    "RubricStrategy",
    "RubricVerdict",
    "SubAgentRubric",
]
