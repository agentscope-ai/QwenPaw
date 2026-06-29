# -*- coding: utf-8 -*-
"""Ultrawork — Parallel Delegation Loop plugin."""
import logging
from pathlib import Path
from typing import Any, Dict

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_SKILL_MD = Path(__file__).parent / "SKILL.md"

LOOP_SKILL_CONFIG: Dict[str, Any] = {
    "name": "ultrawork",
    "slash_command": "ultrawork",
    "description": (
        "Parallel delegation — " "decompose todos and complete them all."
    ),
    "skill_prompt": "",
    "rubric": {
        "mode": "hard_check",
        "check_expression": ("todos.every(t => t.done === true)"),
        "continuation_prompt": (
            "There are still incomplete todos. " "Continue working."
        ),
    },
    "state": {
        "mode": "json_file",
        "filename": "ultrawork-state.json",
        "schema_hint": "todos: [{id, title, done}]",
    },
    "doom_loop": {
        "enabled": True,
        "window_size": 4,
        "similarity_threshold": 0.8,
        "action": "hitl",
    },
    "safety": {
        "max_iterations": 25,
        "thinking_only_streak_limit": 3,
        "consecutive_error_limit": 5,
        "budget": {
            "max_tokens": 400000,
            "max_cost_usd": 4.0,
            "on_exceed": "hitl",
        },
    },
    "priority": 100,
}


class UltraworkPlugin:
    """Ultrawork parallel delegation loop."""

    def register(self, api: PluginApi):
        """Register ultrawork loop skill."""
        from qwenpaw.loop.loader import LoopLoader

        if _SKILL_MD.exists():
            LOOP_SKILL_CONFIG["skill_prompt"] = _SKILL_MD.read_text(
                encoding="utf-8",
            )

        loader = LoopLoader(api)
        loader.load_from_dict(LOOP_SKILL_CONFIG)
        logger.info("Registered /ultrawork loop skill")


plugin = UltraworkPlugin()
