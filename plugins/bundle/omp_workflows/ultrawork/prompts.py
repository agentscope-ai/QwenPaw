# -*- coding: utf-8 -*-
"""Ultrawork continuation prompt templates."""

from __future__ import annotations

from pathlib import Path

from ..shared.constants import ULTRAWORK_MAX_ITERATIONS
from ..shared.role_prompts import format_batch_item, tools_literal


def build_continuation(
    loop_dir: Path,
    iteration: int = 0,
    max_iterations: int = ULTRAWORK_MAX_ITERATIONS,
) -> str:
    """Build the controller prompt for the working phase."""
    item1 = format_batch_item(
        "executor",
        "<sub-task 1>",
        fork=True,
    )
    item2 = format_batch_item(
        "executor",
        "<sub-task 2>",
        fork=True,
    )
    # Shown so controllers know the canonical tool list source.
    executor_tools = tools_literal("executor")
    tools_note = (
        "omit allowed_tools (inherit all)"
        if executor_tools is None
        else f"allowed_tools={executor_tools}"
    )

    return f"""\
You are the Ultrawork parallel execution controller.

Current phase: working
Iteration: {iteration}/{max_iterations}

Use the omp-roles skill for role tool/skill config
(executor: {tools_note}).

Execute:
1. Analyze the task and decompose it into independent sub-tasks.
2. For each sub-task, determine whether it depends on other sub-tasks.
3. Use spawn_subagent batch mode to dispatch all
   independent sub-tasks at once:
   spawn_subagent(task="", batch=[
{item1},
{item2},
     ...
   ])
4. Use check_agent_task to poll each sub-task status
   (wait >= 30s between polls).
5. After all sub-tasks complete, summarize results.
6. Update {loop_dir}/state.json: set phase="done"."""
