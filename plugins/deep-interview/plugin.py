# -*- coding: utf-8 -*-
"""Deep Interview — Socratic questioning loop plugin."""
import logging
from pathlib import Path
from typing import Any, Dict

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_SKILL_MD = Path(__file__).parent / "SKILL.md"

LOOP_SKILL_CONFIG: Dict[str, Any] = {
    "name": "deep-interview",
    "slash_command": "deep-interview",
    "description": (
        "Socratic interview — "
        "deep-dive requirements with ambiguity scoring."
    ),
    "skill_prompt": "",
    "rubric": {
        "mode": "soft_judge",
        "soft_judge_prompt": (
            "Evaluate if the user's requirements "
            "are sufficiently clear. All key questions "
            "answered? Ambiguity score below 0.3?"
        ),
        "continuation_prompt": (
            "There are still ambiguous areas in the "
            "requirements. Continue asking questions."
        ),
    },
    "state": {
        "mode": "none",
    },
    "doom_loop": {
        "enabled": True,
        "window_size": 5,
        "similarity_threshold": 0.7,
        "action": "hitl",
        "hitl_message": (
            "Agent is repeatedly asking similar "
            "questions. Please intervene."
        ),
    },
    "safety": {
        "max_iterations": 20,
        "thinking_only_streak_limit": 5,
        "consecutive_error_limit": 3,
        "budget": {
            "max_tokens": 100000,
            "max_cost_usd": 1.0,
            "on_exceed": "force_stop",
        },
    },
    "priority": 120,
}


class DeepInterviewPlugin:
    """Deep interview Socratic loop."""

    def register(self, api: PluginApi):
        """Register deep-interview loop skill."""
        from qwenpaw.loop.loader import LoopLoader

        if _SKILL_MD.exists():
            LOOP_SKILL_CONFIG["skill_prompt"] = _SKILL_MD.read_text(
                encoding="utf-8",
            )

        loader = LoopLoader(api)
        loader.load_from_dict(LOOP_SKILL_CONFIG)
        logger.info(
            "Registered /deep-interview loop skill",
        )


plugin = DeepInterviewPlugin()
