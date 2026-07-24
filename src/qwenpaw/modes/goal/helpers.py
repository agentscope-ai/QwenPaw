# -*- coding: utf-8 -*-
"""Goal-mode module-level helper functions.

Separated from goal_mode.py for maintainability.
"""
from __future__ import annotations

import logging
from typing import Any

from agentscope.message import Msg, TextBlock

logger = logging.getLogger(__name__)


def rewrite_user_msg(ctx: Any, text: str) -> None:
    """Replace last user message content with *text*."""
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if not isinstance(last, Msg):
        return
    last.content = [
        TextBlock(type="text", text=text),
    ]


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


def create_doom_loop_gate(
    workspace: object,
) -> Any:
    """Create DoomLoopGate from agent config.

    Returns None if doom loop detection is disabled
    or config is unavailable.
    """
    try:
        from ...loop.gates import DoomLoopGate

        agent_cfg = getattr(
            workspace,
            "agent_config",
            None,
        )
        if agent_cfg is None:
            return None
        running = getattr(agent_cfg, "running", None)
        if running is None:
            return None
        loop_cfg = getattr(running, "loop", None)
        if loop_cfg is None:
            return None
        doom_cfg = getattr(
            loop_cfg,
            "doom_loop",
            None,
        )
        if doom_cfg is None or not doom_cfg.enabled:
            return None

        return DoomLoopGate(
            window_size=doom_cfg.window_size,
            similarity_threshold=(doom_cfg.similarity_threshold),
            stages=doom_cfg.stages,
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "DoomLoopGate creation skipped",
            exc_info=True,
        )
        return None


def create_completion_gate(
    workspace: object,
) -> Any:
    """Create QualitativeRubricGate from config.

    Returns None when the rubric completion check
    is disabled or the config is missing.
    """
    try:
        from ...loop.gates import (
            QualitativeRubricGate,
        )

        agent_cfg = getattr(
            workspace,
            "agent_config",
            None,
        )
        if agent_cfg is None:
            return None
        running = getattr(agent_cfg, "running", None)
        if running is None:
            return None
        loop_cfg = getattr(running, "loop", None)
        if loop_cfg is None:
            return None
        rubric_cfg = getattr(
            loop_cfg,
            "rubric",
            None,
        )
        if rubric_cfg is None or not rubric_cfg.enabled:
            return None

        return QualitativeRubricGate(
            rubric=rubric_cfg.prompt,
            max_evaluations=(rubric_cfg.max_interventions),
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "QualitativeRubricGate creation skipped",
            exc_info=True,
        )
        return None


__all__ = [
    "create_completion_gate",
    "create_doom_loop_gate",
    "register_goal_tools_governance",
    "rewrite_user_msg",
]
