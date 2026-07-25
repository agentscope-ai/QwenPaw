# -*- coding: utf-8 -*-
"""Ralph continuation prompt templates."""

from __future__ import annotations

from pathlib import Path

from ..shared.role_prompts import format_spawn_call, resolve_role


def build_continuation(
    iteration: int,
    max_iterations: int,
    critic_type: str,
    no_deslop: bool,
    loop_dir: Path,
    prd_summary: str,
) -> str:
    """Build the controller continuation for a Ralph iteration."""
    deslop_block = ""
    if not no_deslop:
        deslop_block = (
            "7.5. Run deslop cleanup on changed files.\n"
            "7.6. Re-run tests/build/lint to verify "
            "no regressions from deslop.\n"
        )

    reviewer = resolve_role(critic_type)
    # Sequential story loop runs in the main workspace (no fork): each
    # story must land on the shared tree before the next story starts.
    executor_spawn = format_spawn_call(
        "executor",
        "Implement the following user story:\\n"
        "<story details + acceptance criteria>",
        fork=False,
    )
    reviewer_spawn = format_spawn_call(
        reviewer,
        "REVIEW: Verify the complete implementation against the PRD...",
    )

    return f"""\
Ralph PRD-driven loop — iteration {iteration}/{max_iterations}.
{prd_summary}

Use the omp-roles skill for role tool/skill config.

Execute the current step:

1. Read {loop_dir}/prd.json for the user stories list.
2. Pick the highest-priority story with passes=false.
3. Dispatch an executor subagent to implement it:
{executor_spawn}
4. After completion, verify every acceptance criterion (run tests/build/lint).
5. If verified, update prd.json: set passes=true for this story.
   Write progress to {loop_dir}/progress.txt.
6. If all stories pass, proceed to step 7. Otherwise loop to step 2.
7. Dispatch a {reviewer} reviewer to verify the overall implementation:
{reviewer_spawn}
{deslop_block}\
8. When the reviewer approves, update {loop_dir}/state.json:
   set completed=true (required for the loop to terminate).
9. Then report completion to the user.

WARNING — POLITE-STOP ANTI-PATTERN:
After the reviewer approves, do NOT stop to report results.
Continue immediately through deslop -> regression check -> cleanup.
Stopping mid-chain to ask the user is a known failure mode."""


def build_initial_prd_prompt(task: str, loop_dir: Path) -> str:
    """Build the prompt for the initial PRD creation step."""
    return f"""\
Ralph activated. Task: {task}

Step 1 — PRD Setup:
1. Analyze the task and create {loop_dir}/prd.json with this structure:
   {{
     "title": "<task title>",
     "stories": [
       {{
         "id": "S1",
         "title": "<story title>",
         "description": "<what to implement>",
         "acceptance_criteria": ["<criterion 1>", "..."],
         "priority": 1,
         "passes": false
       }}
     ]
   }}
2. Break the task into concrete user stories
   with measurable acceptance criteria.
3. After creating prd.json, begin the implementation loop."""
