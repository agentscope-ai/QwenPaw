# -*- coding: utf-8 -*-
"""Detect repeated identical non-plan tool calls during plan execution.

When a subtask is ``in_progress``, the model sometimes re-runs the same
shell command or file read in a loop without calling ``finish_subtask``.
This guard blocks the Nth identical call and returns an error that routes
through the same path as :func:`check_plan_tool_gate` so the model must
advance the plan instead.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Block when the same fingerprint is seen this many times in a row
# (allows three identical successful runs, stops the fourth).
_REPEAT_THRESHOLD = 4

# Plan notebook tools: do not count toward repetition;
# ``finish_subtask`` clears.
_PLAN_TOOL_NAMES = frozenset(
    {
        "finish_subtask",
        "update_subtask_state",
        "finish_plan",
        "create_plan",
        "revise_current_plan",
        "view_subtasks",
        "view_historical_plans",
        "recover_historical_plan",
    },
)


def _tool_fingerprint(tool_name: str, tool_input: Any) -> str:
    """Stable short string for comparing 'same' tool invocations."""
    if isinstance(tool_input, dict):
        try:
            payload = json.dumps(
                tool_input,
                sort_keys=True,
                ensure_ascii=False,
            )
        except TypeError:
            payload = str(tool_input)
    else:
        payload = str(tool_input)
    return f"{tool_name}:{payload[:800]}"


def _reset_repeat_state(plan_notebook) -> None:
    plan_notebook._qwenpaw_repeat_fp = None  # pylint: disable=protected-access
    plan_notebook._qwenpaw_repeat_count = 0  # pylint: disable=protected-access


def check_plan_repeat_guard(
    plan_notebook,
    tool_name: str,
    tool_input: Any,
) -> str | None:
    """If the same non-plan tool would run too many times in a row, block.

    Only active when ``current_plan`` exists and at least one subtask is
    ``in_progress``.  Resets when ``finish_subtask`` is invoked.
    """
    if plan_notebook is None:
        return None
    plan = getattr(plan_notebook, "current_plan", None)
    if plan is None:
        return None
    if not any(st.state == "in_progress" for st in plan.subtasks):
        return None

    if tool_name in _PLAN_TOOL_NAMES:
        if tool_name == "finish_subtask":
            _reset_repeat_state(plan_notebook)
        return None

    if not hasattr(plan_notebook, "_qwenpaw_repeat_fp"):
        _reset_repeat_state(plan_notebook)

    fp = _tool_fingerprint(tool_name, tool_input)
    last_fp = getattr(plan_notebook, "_qwenpaw_repeat_fp", None)
    # pylint: disable=protected-access
    if fp == last_fp:
        plan_notebook._qwenpaw_repeat_count = (
            int(
                getattr(
                    plan_notebook,
                    "_qwenpaw_repeat_count",
                    0,
                ),
            )
            + 1
        )
    else:
        plan_notebook._qwenpaw_repeat_fp = fp
        plan_notebook._qwenpaw_repeat_count = 1

    count = int(getattr(plan_notebook, "_qwenpaw_repeat_count", 0))
    if count >= _REPEAT_THRESHOLD:
        logger.warning(
            "Plan repeat guard: blocking identical tool=%s "
            "after %d consecutive "
            "calls (agent_id context on notebook)",
            tool_name,
            count,
        )
        return (
            "Repeated identical tool calls while a plan subtask is "
            "in_progress. "
            "If the last outputs already show success (e.g. tests "
            "passed, syntax "
            "OK), you MUST call 'finish_subtask' now with the current "
            "subtask_idx and a short outcome — do not run the same "
            "command again. "
            "If something failed, use a different approach or report "
            "the error in "
            "the finish_subtask outcome."
        )
    return None
