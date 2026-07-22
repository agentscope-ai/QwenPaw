# -*- coding: utf-8 -*-
"""Team pipeline continuation prompt templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..shared.role_prompts import (
    format_batch_item,
    format_spawn_call,
    tools_literal,
)


@dataclass(frozen=True)
class TeamPromptCtx:
    """Typed context for Team phase prompt builders."""

    loop_dir: Path
    iteration: int
    max_iterations: int
    agent_count: int = 3
    agent_role: str = "executor"
    fix_attempts: int = 0
    max_fix_attempts: int = 3


def build_continuation(
    phase: str,
    iteration: int,
    max_iterations: int,
    agent_count: int,
    agent_role: str,
    loop_dir: Path,
    fix_attempts: int = 0,
    max_fix_attempts: int = 3,
) -> str:
    """Return the controller prompt for the current pipeline phase."""
    ctx = TeamPromptCtx(
        loop_dir=loop_dir,
        iteration=iteration,
        max_iterations=max_iterations,
        agent_count=agent_count,
        agent_role=agent_role,
        fix_attempts=fix_attempts,
        max_fix_attempts=max_fix_attempts,
    )
    builders = {
        "plan": _plan,
        "prd": _prd,
        "exec": _exec,
        "verify": _verify,
        "fix": _fix,
    }
    fn = builders.get(phase)
    if fn is None:
        return f"Unknown phase: {phase}. Update state.json."
    return fn(ctx)


def _plan(ctx: TeamPromptCtx) -> str:
    explore = format_spawn_call(
        "explore",
        "Explore the codebase and map relevant "
        "files, modules, and dependencies.",
    )
    planner = format_spawn_call(
        "planner",
        "Create an implementation plan with "
        "task breakdown and dependencies...",
    )
    return f"""\
Team Pipeline Controller — phase: plan.
Pipeline iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Dispatch an explore subagent to map the codebase:
{explore}
2. After exploration, dispatch a planner subagent:
{planner}
3. Write the plan to {ctx.loop_dir}/handoffs/plan.md.
4. Update {ctx.loop_dir}/state.json: set current_phase="prd"."""


def _prd(ctx: TeamPromptCtx) -> str:
    analyst = format_spawn_call(
        "analyst",
        (
            "Read the plan and define acceptance "
            "criteria for each sub-task..."
        ),
    )
    return f"""\
Team Pipeline Controller — phase: prd.
Pipeline iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Read {ctx.loop_dir}/handoffs/plan.md for the task breakdown.
2. Dispatch an analyst subagent:
{analyst}
3. Write the PRD to {ctx.loop_dir}/handoffs/prd.md.
4. Update {ctx.loop_dir}/state.json: set current_phase="exec"."""


def _exec(ctx: TeamPromptCtx) -> str:
    role = ctx.agent_role
    item = format_batch_item(
        role,
        f"<sub-task 1>\\nWrite your result to "
        f"{ctx.loop_dir}/results/agent-001.json",
        fork=True,
    )
    tools_note = tools_literal(role)
    tools_hint = (
        "omit allowed_tools (inherit all)"
        if tools_note is None
        else f"allowed_tools={tools_note}"
    )
    return f"""\
Team Pipeline Controller — phase: exec.
Pipeline iteration: {ctx.iteration}/{ctx.max_iterations}
Workers: {ctx.agent_count}, Role: {role} ({tools_hint})

Use the omp-roles skill for role tool/skill config.

Execute:
1. Read {ctx.loop_dir}/handoffs/prd.md for sub-tasks and acceptance criteria.
2. Dispatch {ctx.agent_count} workers via batch mode:
   spawn_subagent(task="", batch=[
{item},
     ...repeat for each worker...
   ])
3. Poll each worker with check_agent_task (wait >= 30s between polls).
4. After all complete, read {ctx.loop_dir}/results/ files and summarize.
5. Write the summary to {ctx.loop_dir}/handoffs/exec-summary.md.
6. Update {ctx.loop_dir}/state.json: set current_phase="verify"."""


def _verify(ctx: TeamPromptCtx) -> str:
    verifier = format_batch_item(
        "verifier",
        "VERIFY: Check code changes for correctness and completeness...",
    )
    security = format_batch_item(
        "security-reviewer",
        "SECURITY REVIEW: Check for security vulnerabilities...",
    )
    code = format_batch_item(
        "code-reviewer",
        "CODE REVIEW: Review code quality and conventions...",
    )
    return f"""\
Team Pipeline Controller — phase: verify.
Pipeline iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Read {ctx.loop_dir}/handoffs/exec-summary.md.
2. Dispatch three reviewers via batch mode:
   spawn_subagent(task="", batch=[
{verifier},
{security},
{code}
   ])
3. If ALL pass -> update {ctx.loop_dir}/state.json: \
set current_phase="completed".
4. If any fail -> write report to {ctx.loop_dir}/handoffs/verify-report.md
   -> update state.json: set current_phase="fix"."""


def _fix(ctx: TeamPromptCtx) -> str:
    debugger = format_spawn_call(
        "debugger",
        "Fix the following issues from verification:\\n<issues>",
    )
    return f"""\
Team Pipeline Controller — phase: fix.
Pipeline iteration: {ctx.iteration}/{ctx.max_iterations}
Fix attempt: {ctx.fix_attempts}/{ctx.max_fix_attempts}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Read {ctx.loop_dir}/handoffs/verify-report.md for failure details.
2. Dispatch a debugger subagent to fix the issues:
{debugger}
3. After fix, update {ctx.loop_dir}/state.json: set current_phase="verify"."""
