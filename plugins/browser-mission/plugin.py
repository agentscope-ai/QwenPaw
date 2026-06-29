# -*- coding: utf-8 -*-
"""Browser Mission — Browser Automation Loop plugin."""
from qwenpaw.loop.base_plugin import BaseLoopPlugin


class BrowserMissionPlugin(BaseLoopPlugin):
    """Browser Mission browser automation loop."""

    LOOP_SKILL_CONFIG = {
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
                "The browser task is not yet "
                "complete. Review the current page "
                "state and continue with the next "
                "action."
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
                "Please intervene or adjust the "
                "task."
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


plugin = BrowserMissionPlugin()
