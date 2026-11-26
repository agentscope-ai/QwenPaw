# -*- coding: utf-8 -*-
"""Goal-mode module-level helper functions.

Separated from goal_mode.py for maintainability.
"""

from __future__ import annotations

import logging
from ...loop.gates import DoomLoopGate, QualitativeRubricGate
from ...config.config import SessionLoopConfig


logger = logging.getLogger(__name__)


def register_goal_tools_governance() -> None:
    """Register goal tools with governance."""
    try:
        from ...governance.tool_registry import (
            DEFAULT_REGISTRY,
            register_tool_governance,
        )

        for py, policy in (
            ("get_goal", "GetGoal"),
            ("create_goal", "CreateGoal"),
            ("update_goal", "UpdateGoal"),
        ):
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=py,
                tool_type="internal",
                policy_name=policy,
                owner="builtin",
            )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Goal governance registration skipped",
            exc_info=True,
        )


def create_doom_loop_gate(config: SessionLoopConfig) -> DoomLoopGate | None:
    """Build the enabled doom-loop gate from this session's settings."""
    doom = config.doom_loop
    if not doom.enabled:
        return None
    return DoomLoopGate(
        window_size=doom.window_size,
        similarity_threshold=doom.similarity_threshold,
        stages=doom.stages,
    )


def create_completion_gate(
    config: SessionLoopConfig,
) -> QualitativeRubricGate | None:
    """Build the completion check when enabled for explicit loop modes."""
    rubric = config.rubric
    if not rubric.enabled or not rubric.in_loop_modes:
        return None
    return QualitativeRubricGate(
        rubric=rubric.prompt,
        max_evaluations=rubric.max_interventions,
        use_decision_model=rubric.use_decision_model,
    )


__all__ = [
    "create_completion_gate",
    "create_doom_loop_gate",
    "register_goal_tools_governance",
]
