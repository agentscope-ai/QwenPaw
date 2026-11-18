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

from ...app.agent_context import get_current_session_id
from ...token_usage.counter import track_session_tokens

if TYPE_CHECKING:
    from .goal_mode import GoalMode

logger = logging.getLogger(__name__)


def make_get_goal(owner: "GoalMode") -> Any:
    """Build the ``get_goal`` tool function."""

    def get_goal() -> str:
        """Get the current goal status, budgets, and usage."""
        session = owner.active_session()
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
                "remaining_tokens": session.remaining_tokens,
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

        session = owner.active_session()
        if session is None:
            return "No active goal to update."

        if status == "complete":
            session.active = False
            session.last_verdict = "satisfied"
            owner.deactivate()
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
        token_budget: int | None = None,
    ) -> str:
        """Create a goal only when explicitly requested.

        Do not infer goals from ordinary tasks.

        Args:
            objective: The concrete objective to pursue.
            token_budget: Token limit; -1 or 0 means unlimited.
                Omit to use the configured default. Set only when requested.
        """
        from .goal_mode import GoalSession

        if not objective or not objective.strip():
            return "Objective is required."

        existing = owner.active_session()
        if existing is not None:
            return "A goal is already active. " "Cancel it first with /cancel."

        key = get_current_session_id()
        if key is None:
            return f"An active conversation is required to create a goal."
        if token_budget is not None and token_budget < -1:
            return f"Token budget must be -1 or greater."
        budget = (
            owner.default_max_tokens
            if token_budget is None
            else max(0, token_budget)
        )
        session = GoalSession(
            goal=objective.strip(),
            token_counter=track_session_tokens(key),
            max_tokens=budget,
        )
        owner.sessions[key] = session
        logger.info(
            "Goal created via tool: %s",
            objective.strip()[:80],
        )
        return (
            f"Goal created: {objective.strip()}\n"
            f"Budget: {session.max_iterations} "
            f"iterations, {session.token_budget_display} tokens"
        )

    return create_goal


__all__ = [
    "make_create_goal",
    "make_get_goal",
    "make_update_goal",
]
