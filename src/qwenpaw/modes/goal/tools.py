# -*- coding: utf-8 -*-
"""Goal-mode tools: get_goal, create_goal, update_goal.

Modeled after Codex's goal tools. The agent calls
``update_goal(status="complete")`` to signal completion
rather than relying on text-based detection.
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .goal_mode import GoalMode

logger = logging.getLogger(__name__)


def make_get_goal(owner: "GoalMode") -> Any:
    """Build the ``get_goal`` tool function."""

    def get_goal() -> str:
        """Get the current goal status, budgets, and usage."""
        session = owner.first_active_session()
        if session is None:
            return json.dumps(
                {"status": "no_active_goal"},
            )
        elapsed = time.time() - session.started_at
        return json.dumps(
            {
                "status": "active",
                "goal": session.goal,
                "iteration": session.iteration,
                "max_iterations": session.max_iterations,
                "tokens_used": session.tokens_used,
                "token_budget": session.max_tokens,
                "remaining_tokens": max(
                    0,
                    session.max_tokens - session.tokens_used,
                ),
                "elapsed_seconds": round(elapsed, 1),
                "last_verdict": session.last_verdict,
            },
        )

    return get_goal


def make_update_goal(owner: "GoalMode") -> Any:
    """Build the ``update_goal`` tool function."""

    def update_goal(status: str) -> str:
        """Update the existing goal.

        Args:
            status: "complete" when the objective is fully
                achieved and no required work remains.
                "blocked" only after the same blocking
                condition has recurred for at least three
                consecutive goal turns.
        """
        if status not in ("complete", "blocked"):
            return (
                f"Invalid status '{status}'. "
                f"Must be 'complete' or 'blocked'."
            )

        session = owner.first_active_session()
        if session is None:
            return "No active goal to update."

        if status == "complete":
            session.active = False
            session.last_verdict = "satisfied"
            logger.info(
                "Goal marked complete by agent: %s",
                session.goal[:80],
            )
            return (
                f"Goal marked as complete. "
                f"Iterations used: {session.iteration}"
            )

        # status == "blocked"
        session.active = False
        session.last_verdict = "blocked"
        logger.info(
            "Goal marked blocked by agent: %s",
            session.goal[:80],
        )
        return "Goal marked as blocked. " "The user will be notified."

    return update_goal


def make_create_goal(owner: "GoalMode") -> Any:
    """Build the ``create_goal`` tool function."""

    def create_goal(
        objective: str,
        token_budget: int = 0,
    ) -> str:
        """Create a goal only when explicitly requested.

        Do not infer goals from ordinary tasks.

        Args:
            objective: The concrete objective to pursue.
            token_budget: Positive token budget. Omit
                unless explicitly requested.
        """
        from .goal_mode import GoalSession

        if not objective or not objective.strip():
            return "Objective is required."

        existing = owner.first_active_session()
        if existing is not None:
            return "A goal is already active. " "Cancel it first with /cancel."

        from ...app.agent_context import (
            set_current_session_id,
        )

        key = f"__tool__{int(time.time())}"
        budget = token_budget if token_budget > 0 else owner.default_max_tokens
        session = GoalSession(
            goal=objective.strip(),
            max_tokens=budget,
        )
        owner.sessions[key] = session
        set_current_session_id(key)
        logger.info(
            "Goal created via tool: %s",
            objective.strip()[:80],
        )
        return (
            f"Goal created: {objective.strip()}\n"
            f"Budget: {session.max_iterations} "
            f"iterations, {budget} tokens"
        )

    return create_goal


__all__ = [
    "make_create_goal",
    "make_get_goal",
    "make_update_goal",
]
