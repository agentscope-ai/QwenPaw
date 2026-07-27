# -*- coding: utf-8 -*-
"""Reusable role identity prompts and spawn_subagent formatting."""

from __future__ import annotations

from .constants import ROLE_ALLOWED_TOOLS, ROLE_SKILLS

try:
    from qwenpaw.agents.fork_project import FORK_WORKER_COMMIT_PROTOCOL
except ImportError:  # pragma: no cover - offline / partial installs
    FORK_WORKER_COMMIT_PROTOCOL = (
        "## Fork worktree commit protocol (REQUIRED)\n"
        "Commit all changes in the worktree before finishing.\n"
    )

ROLE_PROMPTS: dict[str, str] = {
    "analyst": (
        "You are a requirements analyst. "
        "Extract concrete requirements, identify hidden constraints, "
        "define measurable acceptance criteria.\n"
        "DO NOT: write code, create files, run commands.\n"
        "OUTPUT: structured requirements in JSON format."
    ),
    "architect": (
        "You are a system architect. "
        "Diagnose failures with root cause analysis, "
        "design system interfaces and module boundaries.\n"
        "OUTPUT: diagnosis with specific fix recommendations."
    ),
    "executor": (
        "You are a code executor. "
        "Implement the assigned task following the design spec. "
        "Run quality checks. Follow existing patterns.\n"
        "OUTPUT: working code + progress report."
    ),
    "qa-tester": (
        "You are an interactive QA tester. "
        "Test CLI/service interactions by starting the service, "
        "running test cases, and verifying expected behavior.\n"
        "OUTPUT: test results with PASS/FAIL per scenario."
    ),
    "security-reviewer": (
        "You are a security reviewer. "
        "Identify vulnerabilities, injection vectors, "
        "auth/authz weaknesses, and data exposure risks.\n"
        "DO NOT modify any project files.\n"
        "OUTPUT: security findings with severity ratings."
    ),
    "code-reviewer": (
        "You are a code reviewer. "
        "Review code quality, correctness, maintainability, "
        "and adherence to project conventions.\n"
        "DO NOT modify any project files.\n"
        "OUTPUT: review findings with actionable feedback."
    ),
    "critic": (
        "You are a plan/design critic. "
        "Challenge assumptions, find gaps, identify risks.\n"
        "DO NOT create plans or write code.\n"
        "OUTPUT: critique with specific concerns and alternatives."
    ),
    "planner": (
        "You are a strategic planner. "
        "Create implementation plans from specifications. "
        "Define task breakdown and dependency order.\n"
        "DO NOT write implementation code.\n"
        "OUTPUT: ordered task list with dependencies."
    ),
    "explore": (
        "You are a code explorer. "
        "Search and read the codebase to map structure, "
        "dependencies, and relevant code locations.\n"
        "DO NOT modify any files.\n"
        "OUTPUT: structured findings with file paths and relationships."
    ),
    "debugger": (
        "You are a debugging expert. "
        "Perform root cause analysis on build/test failures. "
        "Apply targeted fixes.\n"
        "DO NOT add new features.\n"
        "OUTPUT: root cause + applied fix summary."
    ),
    "verifier": (
        "You are an adversarial verifier. "
        "Your job is to BREAK the implementation. "
        "Try every edge case, invalid input, and race condition.\n"
        "DO NOT modify any project files.\n"
        "OUTPUT: VERDICT: PASS/FAIL/PARTIAL with evidence."
    ),
}

# UX / flag aliases → ROLE_PROMPTS keys.
_ROLE_ALIASES = {
    "codex": "critic",  # Ralph --critic=codex
    "ralph": "executor",  # Team `/team ralph ...`
}


def resolve_role(role: str) -> str:
    """Map *role* (and aliases) onto a known ROLE_PROMPTS key."""
    key = _ROLE_ALIASES.get(role, role)
    if key in ROLE_PROMPTS:
        return key
    return "executor"


def get_role_prompt(role: str) -> str:
    """Return the prompt fragment for *role*, falling back to executor."""
    return ROLE_PROMPTS[resolve_role(role)]


def build_worker_prompt(
    role: str,
    task: str,
    context: str = "",
    *,
    fork: bool = False,
) -> str:
    """Build a complete worker prompt for spawn_subagent's *task* param."""
    parts = [get_role_prompt(role)]
    if fork:
        parts.append("\n" + FORK_WORKER_COMMIT_PROTOCOL)
    parts.append(f"\n## Task\n{task}")
    if context:
        parts.append(f"\n## Context\n{context}")
    return "\n".join(parts)


def tools_literal(role: str) -> str | None:
    """Return a Python-list literal for *role*'s tools, or None to omit."""
    tools = ROLE_ALLOWED_TOOLS.get(resolve_role(role))
    if tools is None:
        return None
    inner = ", ".join(f'"{t}"' for t in tools)
    return f"[{inner}]"


def skills_literal(role: str) -> str | None:
    """Return a Python-list literal for *role*'s skills, or None to omit."""
    skills = ROLE_SKILLS.get(resolve_role(role))
    if skills is None:
        return None
    inner = ", ".join(f'"{s}"' for s in skills)
    return f"[{inner}]"


def format_spawn_call(
    role: str,
    task_body: str,
    *,
    fork: bool = False,
    background: bool = True,
    indent: str = "   ",
) -> str:
    """Format a ``spawn_subagent(...)`` example for controller prompts.

    The *task* argument embeds the role identity from
    :func:`build_worker_prompt` so prompts stay aligned with
    ``ROLE_PROMPTS`` / ``omp-roles`` skill config.
    """
    # Keep the example readable: show role identity + task placeholder.
    task_preview = (
        f"<role:{resolve_role(role)} identity from omp-roles>\\n\\n"
        f"## Task\\n{task_body}"
    )
    pad = indent
    lines = [
        f"{pad}spawn_subagent(",
        f'{pad}    task="{task_preview}",',
    ]
    tools = tools_literal(role)
    if tools is not None:
        lines.append(f"{pad}    allowed_tools={tools},")
    skills = skills_literal(role)
    if skills is not None:
        lines.append(f"{pad}    skills={skills},")
    if fork:
        lines.append(f"{pad}    fork=True,")
    if background:
        lines.append(f"{pad}    background=True,")
    lines.append(f"{pad})")
    return "\n".join(lines)


def format_batch_item(
    role: str,
    task_body: str,
    *,
    fork: bool = False,
    indent: str = "     ",
) -> str:
    """Format one batch-mode dict entry for controller prompts."""
    pad = indent
    task_preview = (
        f"<role:{resolve_role(role)} identity from omp-roles>\\n\\n"
        f"## Task\\n{task_body}"
    )
    lines = [
        f"{pad}{{",
        f'{pad}  "task": "{task_preview}",',
    ]
    tools = tools_literal(role)
    if tools is not None:
        lines.append(f'{pad}  "allowed_tools": {tools},')
    skills = skills_literal(role)
    if skills is not None:
        lines.append(f'{pad}  "skills": {skills},')
    if fork:
        lines.append(f'{pad}  "fork": true,')
    lines.append(f"{pad}}}")
    return "\n".join(lines)


FORK_MERGE_PROTOCOL = """\
Fork integration (REQUIRED when any worker used fork=True):
- Each forked worker result includes [FORK_BRANCH: <branch>] and works
  in an isolated git worktree. Workers must commit before finishing;
  `git merge <branch>` only brings commits, not dirty files.
- After ALL workers finish, for each [FORK_BRANCH]:
  1. `git merge --no-ff <branch>` (or cherry-pick the commits) into
     the current branch of the main workspace.
  2. On conflict: resolve or abort. Do NOT advance the workflow phase
     and do NOT report completion while conflicts remain.
- Keep the target workflow phase as-is while merging (do not rewrite
  it back to execution/exec/working).
- If no worker used fork=True, still set forks_integrated=true
  (JSON boolean, not a string).
- After successful integration, update state.json with the JSON
  boolean forks_integrated=true.
- The stop gate REJECTS phase completion until that flag is true AND
  registered fork commits are ancestors of HEAD."""


def fork_merge_instructions(indent: str = "") -> str:
    """Return the fork merge protocol block, optionally indented."""
    if not indent:
        return FORK_MERGE_PROTOCOL
    return "\n".join(
        indent + line for line in FORK_MERGE_PROTOCOL.splitlines()
    )
