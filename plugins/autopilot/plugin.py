# -*- coding: utf-8 -*-
"""Autopilot — Multi-Phase Autonomous Execution plugin."""
from qwenpaw.loop.base_plugin import BaseLoopPlugin


class AutopilotPlugin(BaseLoopPlugin):
    """Autopilot multi-phase execution loop."""

    LOOP_SKILL_CONFIG = {
        "name": "autopilot",
        "slash_command": "autopilot",
        "description": (
            "Multi-phase autonomous execution — "
            "plan, execute, QA, validate."
        ),
        "skill_prompt": "",
        "rubric": {
            "mode": "hard_check",
            "check_expression": "phase === 'complete'",
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
                "phase: expansion|planning|execution" "|qa|validation|complete"
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


plugin = AutopilotPlugin()
