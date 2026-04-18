# -*- coding: utf-8 -*-
"""Mission Mode message handler.

Detects ``/mission`` in the user query, sets up state files, and rewrites
the user message so the main agent enters Mission Mode.

Returns:
    - ``str`` for info sub-commands (status, list, help) — displayed to
      the user immediately.
    - ``dict`` for a new mission start — contains ``mission_phase``,
      ``loop_dir``, ``max_iterations`` so the runner can delegate to
      :mod:`~qwenpaw.agents.mission.mission_runner`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .prompts import build_master_prompt
from .state import (
    create_loop_dir,
    detect_git_context,
    get_active_loop_dir,
    init_progress_txt,
    list_loop_dirs,
    read_loop_config,
    read_prd,
    write_loop_config,
    write_task_md,
)

logger = logging.getLogger(__name__)

MISSION_COMMANDS = frozenset({"/mission"})

# Defaults and limits for --max-iterations
_DEFAULT_MAX_ITERATIONS = 20
_MIN_MAX_ITERATIONS = 1
_MAX_MAX_ITERATIONS = 100


def is_mission_command(query: str | None) -> bool:
    """Return True if the query starts with a mission trigger command."""
    if not query or not isinstance(query, str):
        return False
    token = query.strip().split(None, 1)[0].lower()
    return token in MISSION_COMMANDS


def _parse_mission_args(query: str) -> dict[str, Any]:
    """Parse ``/mission [task text] [--verify CMD] [--max-iterations N]``."""
    parts = query.strip().split(None, 1)
    raw = parts[1] if len(parts) > 1 else ""

    args: dict[str, Any] = {
        "task_text": "",
        "verify_commands": "",
        "max_iterations": _DEFAULT_MAX_ITERATIONS,
    }

    tokens = raw.split()
    task_parts: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "--verify" and i + 1 < len(tokens):
            args["verify_commands"] = tokens[i + 1]
            i += 2
        elif tokens[i] == "--max-iterations" and i + 1 < len(tokens):
            try:
                args["max_iterations"] = int(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            task_parts.append(tokens[i])
            i += 1

    args["task_text"] = " ".join(task_parts)

    # Clamp max_iterations to a sane range
    max_iters = args["max_iterations"]
    if max_iters < _MIN_MAX_ITERATIONS:
        logger.warning(
            "Mission: --max-iterations %d too low, clamping to %d",
            max_iters,
            _MIN_MAX_ITERATIONS,
        )
        args["max_iterations"] = _MIN_MAX_ITERATIONS
    elif max_iters > _MAX_MAX_ITERATIONS:
        logger.warning(
            "Mission: --max-iterations %d too high, clamping to %d",
            max_iters,
            _MAX_MAX_ITERATIONS,
        )
        args["max_iterations"] = _MAX_MAX_ITERATIONS

    return args


async def handle_mission_command(  # pylint: disable=too-many-return-statements
    query: str,
    msgs: list,
    workspace_dir: Path,
    agent_id: str,
    rewrite_fn: Any,
    session_id: str = "",
) -> str | dict[str, Any]:
    """Process a ``/mission`` command.

    Returns:
        ``str`` — display text for info sub-commands.
        ``dict`` — phase info when a new loop is created
            and Phase 1 should begin.
    """
    args = _parse_mission_args(query)
    task_text = args["task_text"]

    # --- Sub-commands that return info without starting a loop -----------

    if task_text.strip().lower() == "status":
        # Default: session-bound lookup
        loop_dir = get_active_loop_dir(workspace_dir, session_id)
        if loop_dir is None:
            return (
                "**Mission Status**: No active mission for this session.\n\n"
                "Use `/mission list` to see all missions in this workspace."
            )
        prd = read_prd(loop_dir)
        cfg = read_loop_config(loop_dir)
        stories = prd.get("userStories", [])
        passed = sum(1 for s in stories if s.get("passes"))
        git_label = "n/a"
        if cfg.get("git_installed"):
            git_label = "installed"
            if cfg.get("is_git_repo"):
                git_label += f", repo (branch `{cfg.get('branch_name', '?')}`)"

        loop_session = cfg.get("session_id", "N/A")
        phase = cfg.get("current_phase", "unknown")

        lines = [
            f"**Mission Status** — `{loop_dir.name}`",
            f"- Session: `{loop_session}`",
            f"- Phase: `{phase}`",
            f"- Project: {prd.get('project', 'N/A')}",
            f"- Progress: {passed}/{len(stories)} stories passed",
            f"- Loop dir: `{loop_dir}`",
            f"- Git: {git_label}",
        ]
        for s in stories:
            mark = "✅" if s.get("passes") else "⬜"
            lines.append(f"  {mark} {s['id']}: {s['title']}")
        return "\n".join(lines)

    if task_text.strip().lower() == "list":
        loops = list_loop_dirs(workspace_dir)
        if not loops:
            return "**Mission Mode**: No missions found."
        lines = ["**Missions**\n"]
        for lp in loops:
            mark = "✅" if lp["all_passed"] else "🔄"
            branch_hint = f" `{lp['branch']}`" if lp.get("branch") else ""
            lines.append(
                f"- {mark} `{lp['loop_id']}` — "
                f"{lp['description'] or lp['project']} "
                f"({lp['stories_passed']}/{lp['stories_total']})"
                f"{branch_hint}",
            )
        return "\n".join(lines)

    # --- Help / invalid queries -------------------------------------------

    if not task_text or len(task_text.strip()) < 5:
        return (
            "**Mission Mode**\n\n"
            "Usage:\n"
            "- `/mission <task description>` — start a new mission\n"
            "- `/mission status` — show current mission progress\n"
            "- `/mission list` — list all missions\n\n"
            "Options:\n"
            "- `--verify <command>` — verification command (e.g. `pytest`)\n"
            f"- `--max-iterations <n>` — max Phase 2 iterations "
            f"(range: {_MIN_MAX_ITERATIONS}-{_MAX_MAX_ITERATIONS}, "
            f"default: {_DEFAULT_MAX_ITERATIONS})\n\n"
            "⚠️ **Security Warning**:\n"
            "- Worker agents bypass security guards (auto-disabled via "
            "`--background`)\n"
            "- Sensitive operations (shell, file writes) execute without "
            "approval\n"
            "- **Only use in trusted codebases**\n\n"
            "**Note**: Task description must be at least 5 characters."
        )

    # Block meta/question queries that aren't actual tasks
    task_lower = task_text.lower()
    meta_keywords = [
        "是什么",
        "什么是",
        "怎么用",
        "如何使用",
        "做什么",
        "干什么",
        "what is",
        "how to use",
        "what does",
        "what do",
    ]
    if any(kw in task_lower for kw in meta_keywords):
        return (
            "**Mission Mode**\n\n"
            "It looks like you're asking a question about "
            "Mission Mode itself, rather than describing a task.\n\n"
            "Mission Mode is for executing complex tasks. Examples:\n"
            "- `/mission 实现用户认证系统，包含JWT和测试`\n"
            "- `/mission Add a notification system with bell icon`\n"
            "- `/mission 重构数据库层，使用 repository 模式`\n\n"
            "For info: `/mission status` or `/mission list`"
        )

    # --- Set up state files and start loop --------------------------------

    loop_dir = create_loop_dir(workspace_dir)
    write_task_md(loop_dir, task_text)
    init_progress_txt(loop_dir)

    git_ctx = await detect_git_context(workspace_dir)
    max_iterations = args["max_iterations"]

    loop_config: dict[str, Any] = {
        "git_installed": git_ctx["git_installed"],
        "is_git_repo": git_ctx["is_git_repo"],
        "default_branch": git_ctx.get("default_branch", ""),
        "branch_name": "",
        "repo_root": git_ctx.get("repo_root", ""),
        "workspace_dir": str(workspace_dir),
        "max_iterations": max_iterations,
        "current_phase": "prd_generation",
        "session_id": session_id,
        "verify_commands": args["verify_commands"],
    }
    write_loop_config(loop_dir, loop_config)

    logger.info(
        "Mission %s: loop_dir=%s, git_installed=%s, is_repo=%s",
        loop_dir.name,
        loop_dir,
        git_ctx["git_installed"],
        git_ctx["is_git_repo"],
    )

    master_prompt = build_master_prompt(
        loop_dir=str(loop_dir),
        agent_id=agent_id,
        max_iterations=max_iterations,
        verify_commands=args["verify_commands"],
        git_context=git_ctx,
        workspace_dir=str(workspace_dir),
    )

    full_prompt = (
        f"Starting Mission Mode: `{loop_dir.name}`.\n\n"
        f"Task description (also saved in `{loop_dir}/task.md`):\n"
        f"> {task_text}\n\n"
        f"{master_prompt}\n\n"
        f"**Phase 1 — Task Decomposition:**\n"
        f"Explore the workspace and generate prd.json (Step 0).\n"
        f"After writing prd.json, report to the user and wait for "
        f"confirmation.  When the user confirms, update "
        f"`{loop_dir}/loop_config.json` setting "
        f"`current_phase` to `execution_confirmed`."
    )

    rewrite_fn(msgs, full_prompt)

    return {
        "mission_phase": 1,
        "loop_dir": str(loop_dir),
        "max_iterations": max_iterations,
    }
