# -*- coding: utf-8 -*-
"""Deep Interview — Socratic Questioning Loop plugin."""
from qwenpaw.loop.base_plugin import BaseLoopPlugin


class DeepInterviewPlugin(BaseLoopPlugin):
    """Deep Interview socratic questioning loop."""

    LOOP_SKILL_CONFIG = {
        "name": "deep-interview",
        "slash_command": "deep-interview",
        "description": (
            "Socratic questioning loop — " "deep-dive ambiguity until clear."
        ),
        "skill_prompt": "",
        "rubric": {
            "mode": "soft_judge",
            "soft_judge_prompt": (
                "Has the interview gathered enough "
                "requirements with low ambiguity? "
                "Reply satisfied if ambiguity_score "
                "< 0.3, otherwise needs_revision."
            ),
            "continuation_prompt": (
                "The requirements are not yet clear. "
                "Ask 2-3 more targeted questions "
                "about the most ambiguous areas."
            ),
        },
        "state": {
            "mode": "json_file",
            "filename": "deep-interview-state.json",
            "schema_hint": (
                "questions_asked, ambiguity_score, " "gathered_requirements"
            ),
        },
        "doom_loop": {
            "enabled": True,
            "window_size": 5,
            "similarity_threshold": 0.85,
            "action": "hitl",
        },
        "safety": {
            "max_iterations": 15,
            "thinking_only_streak_limit": 3,
            "consecutive_error_limit": 3,
            "budget": {
                "max_tokens": 200000,
                "max_cost_usd": 2.0,
                "on_exceed": "force_stop",
            },
        },
        "priority": 100,
    }


plugin = DeepInterviewPlugin()
