# -*- coding: utf-8 -*-
"""Ralph — Persistent Completion Loop plugin."""
from qwenpaw.loop.base_plugin import BaseLoopPlugin


class RalphPlugin(BaseLoopPlugin):
    """Ralph persistent completion loop."""

    LOOP_SKILL_CONFIG = {
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
                "stories: [{id, title, status, "
                "verified}], current_story_index"
            ),
        },
        "doom_loop": {
            "enabled": True,
            "window_size": 3,
            "similarity_threshold": 0.8,
            "action": "hitl",
            "hitl_message": (
                "Agent repeating same actions in "
                "Ralph loop. Please intervene."
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


plugin = RalphPlugin()
