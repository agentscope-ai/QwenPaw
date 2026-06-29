# -*- coding: utf-8 -*-
"""LLM-as-Judge rubric grader for loop completion."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RubricVerdict(str, Enum):
    """Grader verdicts (LangChain DeepAgents style)."""

    SATISFIED = "satisfied"
    NEEDS_REVISION = "needs_revision"
    FAILED = "failed"
    GRADER_ERROR = "grader_error"
    MAX_ITERATIONS = "max_iterations_reached"


@dataclass
class RubricEvaluation:
    """Result of one grader pass."""

    iteration: int
    verdict: RubricVerdict
    explanation: str = ""
    feedback: str = ""


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


async def run_rubric_grader(
    goal: str,
    agent_output: str,
    iteration: int,
    spawn_fn: Any = None,
) -> RubricEvaluation:
    """Run rubric grading via spawn_subagent.

    Args:
        goal: The user's goal description.
        agent_output: Tail of agent's output text.
        iteration: Current grading iteration.
        spawn_fn: Async callable to spawn a subagent.
            Falls back to tool-level spawn_subagent.

    Returns:
        RubricEvaluation with verdict and feedback.
    """
    if spawn_fn is None:
        from ..agents.tools.agent_management import (
            spawn_subagent,
        )

        spawn_fn = spawn_subagent

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
            fork=False,
            background=False,
            timeout=60,
        )
        return _parse_grader_result(result, iteration)
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


def _parse_grader_result(
    result: Any,
    iteration: int,
) -> RubricEvaluation:
    """Parse the grader subagent's response."""
    text = ""
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, list):
            for block in content:
                if hasattr(block, "text"):
                    text += block.text
                elif isinstance(block, dict):
                    text += block.get("text", "")
        elif isinstance(content, str):
            text = content
    elif isinstance(result, str):
        text = result

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.NEEDS_REVISION,
            explanation="Could not parse grader output",
            feedback=text[:500],
        )

    verdict_str = data.get("verdict", "needs_revision")
    try:
        verdict = RubricVerdict(verdict_str)
    except ValueError:
        verdict = RubricVerdict.NEEDS_REVISION

    return RubricEvaluation(
        iteration=iteration,
        verdict=verdict,
        explanation=data.get("explanation", ""),
        feedback=data.get("feedback", ""),
    )


__all__ = [
    "GRADER_SYSTEM_PROMPT",
    "RubricEvaluation",
    "RubricVerdict",
    "run_rubric_grader",
]
