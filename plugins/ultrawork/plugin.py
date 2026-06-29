# -*- coding: utf-8 -*-
"""Ultrawork — Parallel Delegation Loop plugin."""
from qwenpaw.loop.base_plugin import BaseLoopPlugin


class UltraworkPlugin(BaseLoopPlugin):
    """Ultrawork parallel delegation loop."""

    LOOP_SKILL_CONFIG = {
        "name": "ultrawork",
        "slash_command": "ultrawork",
        "description": (
            "Parallel delegation loop — " "decompose todos and complete each."
        ),
        "skill_prompt": "",
        "rubric": {
            "mode": "hard_check",
            "check_expression": ("todos.every(t => t.done)"),
            "continuation_prompt": (
                "There are still incomplete todos. "
                "Check ultrawork-state.json and "
                "continue with the next item."
            ),
        },
        "state": {
            "mode": "json_file",
            "filename": "ultrawork-state.json",
            "schema_hint": ("todos: [{id, title, done}], " "current_index"),
        },
        "doom_loop": {
            "enabled": True,
            "window_size": 3,
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
        "priority": 95,
    }


plugin = UltraworkPlugin()
