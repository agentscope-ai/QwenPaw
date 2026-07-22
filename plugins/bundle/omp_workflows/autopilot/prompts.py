# -*- coding: utf-8 -*-
"""Autopilot continuation prompt templates — one per phase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..shared.role_prompts import format_batch_item, format_spawn_call

PHASES = ("expansion", "planning", "execution", "qa", "validation", "cleanup")


@dataclass(frozen=True)
class AutopilotPromptCtx:
    """Typed context for Autopilot phase prompt builders."""

    loop_dir: Path
    iteration: int
    max_iterations: int
    skip_qa: bool = False
    skip_validation: bool = False
    validation_round: int = 0
    max_validation_rounds: int = 3


def build_continuation(
    phase: str,
    iteration: int,
    max_iterations: int,
    loop_dir: Path,
    skip_qa: bool = False,
    skip_validation: bool = False,
    validation_round: int = 0,
    max_validation_rounds: int = 3,
) -> str:
    """Return the controller prompt for the current phase."""
    ctx = AutopilotPromptCtx(
        loop_dir=loop_dir,
        iteration=iteration,
        max_iterations=max_iterations,
        skip_qa=skip_qa,
        skip_validation=skip_validation,
        validation_round=validation_round,
        max_validation_rounds=max_validation_rounds,
    )
    builders = {
        "expansion": _expansion,
        "planning": _planning,
        "execution": _execution,
        "qa": _qa,
        "validation": _validation,
    }
    fn = builders.get(phase)
    if fn is None:
        return (
            f"Unknown phase: {phase}. " f"Valid phases: {', '.join(PHASES)}."
        )
    return fn(ctx)


def _expansion(ctx: AutopilotPromptCtx) -> str:
    analyst = format_spawn_call(
        "analyst",
        "Analyze requirements and produce spec.md...",
    )
    return f"""\
Autopilot Controller — phase: expansion.
Iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Analyze the task requirements.
2. Dispatch an analyst subagent to extract requirements:
{analyst}
3. Dispatch an architect subagent to validate and expand the spec.
4. Write the final spec to {ctx.loop_dir}/spec.md.
5. Update {ctx.loop_dir}/state.json: set phase="planning"."""


def _planning(ctx: AutopilotPromptCtx) -> str:
    architect = format_spawn_call(
        "architect",
        "Create implementation plan from spec...",
    )
    critic = format_spawn_call(
        "critic",
        "Review the implementation plan; challenge gaps and risks...",
    )
    return f"""\
Autopilot Controller — phase: planning.
Iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Read {ctx.loop_dir}/spec.md.
2. Dispatch an architect subagent to create an implementation plan:
{architect}
3. Dispatch a critic subagent to review the plan:
{critic}
4. Write the final plan to {ctx.loop_dir}/plan.md.
5. Update {ctx.loop_dir}/state.json: set phase="execution"."""


def _execution(ctx: AutopilotPromptCtx) -> str:
    item1 = format_batch_item("executor", "<task 1 from plan>", fork=True)
    item2 = format_batch_item("executor", "<task 2 from plan>", fork=True)
    return f"""\
Autopilot Controller — phase: execution.
Iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute:
1. Read {ctx.loop_dir}/plan.md for the task list.
2. Identify independent tasks that can run in parallel.
3. Dispatch executor workers via batch mode:
   spawn_subagent(task="", batch=[
{item1},
{item2},
     ...
   ])
4. Poll each worker with check_agent_task (wait >= 30s between polls).
5. After all workers complete, verify outputs.
6. Update {ctx.loop_dir}/state.json: set phase="qa"."""


def _qa(ctx: AutopilotPromptCtx) -> str:
    if ctx.skip_qa:
        return f"""\
Autopilot Controller — phase: qa (SKIPPED via --skip-qa).
Update {ctx.loop_dir}/state.json: set phase="validation"."""

    architect = format_spawn_call(
        "architect",
        "DIAGNOSE FAILURE: paste test output; give root cause + fixes.",
    )
    executor = format_spawn_call(
        "executor",
        "FIX: apply the architect recommendations precisely.",
    )
    return f"""\
Autopilot Controller — phase: qa.
Iteration: {ctx.iteration}/{ctx.max_iterations}

Use the omp-roles skill for role tool/skill config.

Execute the UltraQA-style 3-agent cycle:
1. Run the project test suite.
2. If all tests pass, update {ctx.loop_dir}/state.json: set phase="validation".
3. If tests fail:
   a. Dispatch architect subagent:
{architect}
   b. Dispatch executor subagent:
{executor}
   c. Re-run tests. Repeat up to 5 cycles."""


def _validation(ctx: AutopilotPromptCtx) -> str:
    if ctx.skip_validation:
        return f"""\
Autopilot Controller — phase: validation \
(SKIPPED via --skip-validation).
Update {ctx.loop_dir}/state.json: set phase="cleanup"."""

    verifier = format_batch_item(
        "verifier",
        "REVIEW - Functional Completeness: Verify all spec requirements...",
    )
    security = format_batch_item(
        "security-reviewer",
        "REVIEW - Security: Check for vulnerabilities, injection vectors...",
    )
    code = format_batch_item(
        "code-reviewer",
        "REVIEW - Code Quality: Review quality and maintainability...",
    )
    return f"""\
Autopilot Controller — phase: validation.
Validation round: {ctx.validation_round}/{ctx.max_validation_rounds}

WARNING: You are the Controller — do NOT review
code yourself. Dispatch subagents.
Use the omp-roles skill for role tool/skill config.

Execute parallel validation:
1. Use spawn_subagent batch mode for three reviewers:
   spawn_subagent(task="", batch=[
{verifier},
{security},
{code}
   ])
2. Wait for all reviewers to complete.
3. If ALL approve -> update {ctx.loop_dir}/state.json: set phase="cleanup".
4. If any reject -> fix issues -> increment validation_round -> re-validate.
5. If validation_round > {ctx.max_validation_rounds} -> STOP and report."""
