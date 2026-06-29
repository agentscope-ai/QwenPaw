# -*- coding: utf-8 -*-
"""Autopilot — Multi-Phase Autonomous Execution plugin."""
import logging
from pathlib import Path
from typing import Any, Dict

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_SKILL_MD = Path(__file__).parent / "SKILL.md"

LOOP_SKILL_CONFIG: Dict[str, Any] = {
    "name": "autopilot",
    "slash_command": "autopilot",
    "description": (
        "Multi-phase autonomous execution — " "plan, execute, QA, validate."
    ),
    "skill_prompt": "",
    "rubric": {
        "mode": "hard_check",
        "check_expression": ("phase === 'complete'"),
        "continuation_prompt": (
            "Autopilot is not complete. Current "
            "phase: {phase}. Continue to the "
            "next phase."
        ),
    },
    "state": {
        "mode": "json_file",
        "filename": "autopilot-state.json",
        "schema_hint": (
            "phase: expansion|planning|" "execution|qa|validation|complete"
        ),
    },
    "doom_loop": {
        "enabled": True,
        "window_size": 4,
        "similarity_threshold": 0.75,
        "action": "hitl",
    },
    "safety": {
        "max_iterations": 40,
        "thinking_only_streak_limit": 3,
        "consecutive_error_limit": 5,
        "budget": {
            "max_tokens": 500000,
            "max_cost_usd": 5.0,
            "on_exceed": "hitl",
        },
    },
    "priority": 80,
}


class AutopilotPlugin:
    """Autopilot multi-phase execution loop."""

    def register(self, api: PluginApi):
        """Register autopilot loop skill."""
        from qwenpaw.loop.loader import LoopLoader

        if _SKILL_MD.exists():
            LOOP_SKILL_CONFIG["skill_prompt"] = _SKILL_MD.read_text(
                encoding="utf-8",
            )

        loader = LoopLoader(api)
        loader.load_from_dict(LOOP_SKILL_CONFIG)
        logger.info(
            "Registered /autopilot loop skill",
        )


plugin = AutopilotPlugin()
