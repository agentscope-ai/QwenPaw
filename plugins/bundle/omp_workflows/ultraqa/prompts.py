# -*- coding: utf-8 -*-
"""UltraQA continuation prompt templates."""

from __future__ import annotations

from pathlib import Path

from ..shared.role_prompts import format_spawn_call


def build_continuation(
    cycle: int,
    max_cycles: int,
    goal_type: str,
    custom_cmd: str,
    last_failures: list[str],
    loop_dir: Path,
    interactive: bool = False,
) -> str:
    """Build the controller continuation message for one QA cycle."""
    failures_summary = (
        "\n".join(f"  - {f}" for f in last_failures[-5:])
        if last_failures
        else "  (none)"
    )

    qa_step = (
        _interactive_step()
        if interactive
        else _command_step(goal_type, custom_cmd)
    )
    architect_spawn = format_spawn_call(
        "architect",
        f"DIAGNOSE FAILURE:\\nGoal: {goal_type}\\n"
        "Output: <paste QA output>\\n"
        "Provide root cause analysis and fix recommendations.",
    )
    executor_spawn = format_spawn_call(
        "executor",
        "FIX:\\nIssue: <architect diagnosis>\\n"
        "Files: <affected files>\\n"
        "Apply the fix precisely as recommended.",
    )

    return f"""\
UltraQA cycle {cycle}/{max_cycles}.
Goal: {goal_type}
Previous failures:
{failures_summary}

Use the omp-roles skill for role tool/skill config.
Role identity text is embedded in each spawn task below.

Execute this cycle:

1. {qa_step}
2. If all checks PASS, update {loop_dir}/state.json: set qa_passed=true.
3. If checks FAIL, dispatch an architect subagent to diagnose root cause:
{architect_spawn}
4. After diagnosis completes, dispatch an executor subagent to apply the fix:
{executor_spawn}
5. After the fix, update {loop_dir}/state.json
   with the latest last_failures."""


def _command_step(goal_type: str, custom_cmd: str) -> str:
    cmd_map = {
        "tests": "Run the project test suite.",
        "build": "Run the project build.",
        "lint": "Run the linter.",
        "typecheck": "Run the type checker.",
    }
    if goal_type == "custom" and custom_cmd:
        return f"Run the QA command: `{custom_cmd}`"
    return cmd_map.get(goal_type, "Run the project test suite.")


def _interactive_step() -> str:
    spawn = format_spawn_call(
        "qa-tester",
        "TEST:\\nGoal: <goal>\\nService: <how to start>\\n"
        "Test cases: <scenarios>",
    )
    return "Dispatch a qa-tester subagent for interactive testing:\n" + spawn
