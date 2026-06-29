# -*- coding: utf-8 -*-
"""Browser Mission Loop Plugin.

Registers /browser-mission as a loop skill via PluginApi,
wiring up a LoopSkillConfig with browser-specific rubric,
doom-loop detection, and budget presets.
"""
import logging
from pathlib import Path
from typing import Any, Dict

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_SKILL_MD = Path(__file__).parent / "SKILL.md"

LOOP_SKILL_CONFIG: Dict[str, Any] = {
    "name": "browser-mission",
    "slash_command": "browser-mission",
    "description": (
        "Browser automation loop — "
        "drives a browser to complete "
        "multi-step web tasks."
    ),
    "skill_prompt": "",
    "rubric": {
        "mode": "hard_check",
        "check_expression": (
            "stories.every(s => " "s.passes || s.blocker_reason)"
        ),
        "continuation_prompt": (
            "The browser task is not yet complete. "
            "Review the current page state and "
            "continue with the next action."
        ),
    },
    "state": {
        "mode": "json_file",
        "filename": "browser-mission-state.json",
        "schema_hint": (
            "stories: [{id, title, passes, "
            "blocker_reason}], "
            "iteration_count, last_actions"
        ),
    },
    "doom_loop": {
        "enabled": True,
        "window_size": 6,
        "similarity_threshold": 0.8,
        "action": "hitl",
        "hitl_message": (
            "The browser agent appears stuck "
            "repeating the same actions. "
            "Please intervene or adjust the task."
        ),
    },
    "safety": {
        "max_iterations": 20,
        "thinking_only_streak_limit": 3,
        "consecutive_error_limit": 5,
        "budget": {
            "max_tokens": 300000,
            "max_cost_usd": 3.0,
            "on_exceed": "hitl",
        },
    },
    "priority": 110,
}


class BrowserMissionPlugin:
    """Browser Mission loop skill plugin."""

    def register(self, api: PluginApi):
        """Register the browser-mission loop skill."""
        from qwenpaw.loop.loader import LoopLoader

        if _SKILL_MD.exists():
            LOOP_SKILL_CONFIG["skill_prompt"] = _SKILL_MD.read_text(
                encoding="utf-8",
            )

        loader = LoopLoader(api)
        loader.load_from_dict(LOOP_SKILL_CONFIG)
        logger.info(
            "Registered /browser-mission loop skill",
        )


plugin = BrowserMissionPlugin()
