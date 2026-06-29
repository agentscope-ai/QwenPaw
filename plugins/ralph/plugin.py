# -*- coding: utf-8 -*-
"""Ralph — Persistent Completion Loop plugin."""
import logging
from pathlib import Path
from typing import Any, Dict

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_SKILL_MD = Path(__file__).parent / "SKILL.md"

LOOP_SKILL_CONFIG: Dict[str, Any] = {
    "name": "ralph",
    "slash_command": "ralph",
    "description": (
        "Persistent completion loop — "
        "decompose, execute, verify each story."
    ),
    "skill_prompt": "",
    "rubric": {
        "mode": "hard_check",
        "check_expression": (
            "stories.every(s => " "s.status === 'done' && s.verified)"
        ),
        "continuation_prompt": (
            "There are still unfinished stories. "
            "Check ralph-state.json and continue "
            "working on the next pending story."
        ),
    },
    "state": {
        "mode": "json_file",
        "filename": "ralph-state.json",
        "schema_hint": (
            "stories: [{id, title, status, verified}]," " current_story_index"
        ),
    },
    "doom_loop": {
        "enabled": True,
        "window_size": 3,
        "similarity_threshold": 0.8,
        "action": "hitl",
        "hitl_message": (
            "Agent repeating same actions in Ralph " "loop. Please intervene."
        ),
    },
    "safety": {
        "max_iterations": 30,
        "thinking_only_streak_limit": 3,
        "consecutive_error_limit": 5,
        "budget": {
            "max_tokens": 500000,
            "max_cost_usd": 5.0,
            "on_exceed": "hitl",
        },
    },
    "priority": 90,
}


class RalphPlugin:
    """Ralph persistent completion loop."""

    def register(self, api: PluginApi):
        """Register ralph loop skill."""
        from qwenpaw.loop.loader import LoopLoader

        if _SKILL_MD.exists():
            LOOP_SKILL_CONFIG["skill_prompt"] = _SKILL_MD.read_text(
                encoding="utf-8",
            )

        loader = LoopLoader(api)
        loader.load_from_dict(LOOP_SKILL_CONFIG)
        logger.info("Registered /ralph loop skill")


plugin = RalphPlugin()
