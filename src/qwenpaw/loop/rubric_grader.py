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
    fork: bool = False,
) -> RubricEvaluation:
    """Run rubric grading via spawn_subagent.

    Args:
        goal: The user's goal description.
        agent_output: Tail of agent's output text.
        iteration: Current grading iteration.
        spawn_fn: Async callable to spawn a subagent.
            Falls back to tool-level spawn_subagent.
        fork: If True, run grader in isolated worktree.

    Returns:
        RubricEvaluation with verdict and feedback.
    """
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
                explanation="spawn_subagent unavailable",
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
            fork=fork,
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


_SATISFIED_KEYWORDS = (
    "satisfied",
    "complete",
    "goal met",
    "goal achieved",
    "pass",
)
_FAILED_KEYWORDS = ("failed", "impossible", "cannot")


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


def _parse_grader_result(
    result: Any,
    iteration: int,
) -> RubricEvaluation:
    """Parse grader response via string matching.

    Tries JSON first (for structured responses), then
    falls back to keyword detection in the raw text.
    """
    text = _extract_text(result)
    lower = text.lower()

    # --- try JSON first (best effort) ---
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
                    feedback=data.get("feedback", ""),
                )
    except (ValueError, json.JSONDecodeError):
        pass

    # --- fallback: keyword detection ---
    for kw in _SATISFIED_KEYWORDS:
        if kw in lower:
            return RubricEvaluation(
                iteration=iteration,
                verdict=RubricVerdict.SATISFIED,
                explanation=text[:300],
            )

    for kw in _FAILED_KEYWORDS:
        if kw in lower:
            return RubricEvaluation(
                iteration=iteration,
                verdict=RubricVerdict.FAILED,
                explanation=text[:300],
            )

    return RubricEvaluation(
        iteration=iteration,
        verdict=RubricVerdict.NEEDS_REVISION,
        explanation=text[:300],
        feedback=text[:500],
    )


__all__ = [
    "GRADER_SYSTEM_PROMPT",
    "RubricEvaluation",
    "RubricVerdict",
    "run_rubric_grader",
]
