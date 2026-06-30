# -*- coding: utf-8 -*-
"""Mission Mode command helpers.

Called by ``MissionMode._mission_handler`` (registered via
``SlashCommandRegistry``) to process ``/mission`` sub-commands.
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

MISSION_HELP_TEXT = (
    "Launch mission mode \u2014 decompose, implement, "
    "and verify complex tasks"
)

_DEFAULT_MAX_ITERATIONS = 20
_MIN_MAX_ITERATIONS = 1
_MAX_MAX_ITERATIONS = 100


def parse_mission_args(
    raw_args: str,
) -> dict[str, Any]:
    """Parse ``[task text] [--verify CMD] [--max-iterations N]``.

    Unlike the old ``_parse_mission_args`` this receives
    the text *after* ``/mission`` (no command prefix).
    """
    args: dict[str, Any] = {
        "task_text": "",
        "verify_commands": "",
        "max_iterations": _DEFAULT_MAX_ITERATIONS,
    }

    tokens = raw_args.split()
    task_parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--verify" and i + 1 < len(tokens):
            args["verify_commands"] = tokens[i + 1]
            i += 2
        elif tok == "--max-iterations" and i + 1 < len(tokens):
            try:
                args["max_iterations"] = int(
                    tokens[i + 1],
                )
            except ValueError:
                pass
            i += 2
        else:
            task_parts.append(tok)
            i += 1

    args["task_text"] = " ".join(task_parts)

    max_iters = args["max_iterations"]
    if max_iters < _MIN_MAX_ITERATIONS:
        logger.warning(
            "Mission: --max-iterations %d clamped to %d",
            max_iters,
            _MIN_MAX_ITERATIONS,
        )
        args["max_iterations"] = _MIN_MAX_ITERATIONS
    elif max_iters > _MAX_MAX_ITERATIONS:
        logger.warning(
            "Mission: --max-iterations %d clamped to %d",
            max_iters,
            _MAX_MAX_ITERATIONS,
        )
        args["max_iterations"] = _MAX_MAX_ITERATIONS

    return args


def format_status(
    workspace_dir: Path,
    session_id: str,
) -> str:
    """Return status text for ``/mission status``."""
    loop_dir = get_active_loop_dir(
        workspace_dir,
        session_id,
    )
    if loop_dir is None:
        return (
            "**Mission Status**: No active mission "
            "for this session.\n\n"
            "Use `/mission list` to see all missions."
        )
    prd = read_prd(loop_dir)
    cfg = read_loop_config(loop_dir)
    stories = prd.get("userStories", [])
    passed = sum(1 for s in stories if s.get("passes"))
    git_label = "n/a"
    if cfg.get("git_installed"):
        git_label = "installed"
        if cfg.get("is_git_repo"):
            branch = cfg.get("branch_name", "?")
            git_label += f", repo (branch `{branch}`)"

    lines = [
        f"**Mission Status** \u2014 `{loop_dir.name}`",
        f"- Session: `{cfg.get('session_id', 'N/A')}`",
        f"- Phase: `{cfg.get('current_phase', '?')}`",
        f"- Project: {prd.get('project', 'N/A')}",
        f"- Progress: {passed}/{len(stories)} passed",
        f"- Loop dir: `{loop_dir}`",
        f"- Git: {git_label}",
    ]
    for s in stories:
        mark = "\u2705" if s.get("passes") else "\u2b1c"
        lines.append(
            f"  {mark} {s['id']}: {s['title']}",
        )
    return "\n".join(lines)


def format_list(workspace_dir: Path) -> str:
    """Return list text for ``/mission list``."""
    loops = list_loop_dirs(workspace_dir)
    if not loops:
        return "**Mission Mode**: No missions found."
    lines = ["**Missions**\n"]
    for lp in loops:
        mark = "\u2705" if lp["all_passed"] else "\U0001f504"
        branch = f" `{lp['branch']}`" if lp.get("branch") else ""
        lines.append(
            f"- {mark} `{lp['loop_id']}` \u2014 "
            f"{lp['description'] or lp['project']} "
            f"({lp['stories_passed']}/{lp['stories_total']})"
            f"{branch}",
        )
    return "\n".join(lines)


def format_help() -> str:
    """Return help text for ``/mission`` without args."""
    return (
        "**Mission Mode**\n\n"
        "Usage:\n"
        "- `/mission <task>` \u2014 start a new mission\n"
        "- `/mission status` \u2014 current progress\n"
        "- `/mission list` \u2014 list all missions\n\n"
        "Options:\n"
        "- `--verify <cmd>` \u2014 verification command\n"
        f"- `--max-iterations <n>` \u2014 "
        f"({_MIN_MAX_ITERATIONS}-{_MAX_MAX_ITERATIONS}, "
        f"default {_DEFAULT_MAX_ITERATIONS})\n\n"
        "Task must be at least 5 characters."
    )


_META_KEYWORDS = [
    "\u662f\u4ec0\u4e48",
    "\u4ec0\u4e48\u662f",
    "\u600e\u4e48\u7528",
    "\u5982\u4f55\u4f7f\u7528",
    "\u505a\u4ec0\u4e48",
    "\u5e72\u4ec0\u4e48",
    "what is",
    "how to use",
    "what does",
    "what do",
]


def is_meta_question(task_text: str) -> bool:
    """Return True if the user is asking *about* mission mode."""
    lower = task_text.lower()
    return any(kw in lower for kw in _META_KEYWORDS)


async def start_mission(
    task_text: str,
    workspace_dir: Path,
    agent_id: str,
    session_id: str,
    verify_commands: str,
    max_iterations: int,
) -> tuple[str, Path]:
    """Create state files and return (prompt, loop_dir).

    The caller is responsible for rewriting the user
    message with the returned prompt string, and for
    activating the MissionGate with the loop_dir.
    """
    loop_dir = create_loop_dir(workspace_dir)
    write_task_md(loop_dir, task_text)
    init_progress_txt(loop_dir)

    git_ctx = await detect_git_context(workspace_dir)

    loop_config: dict[str, Any] = {
        "git_installed": git_ctx["git_installed"],
        "is_git_repo": git_ctx["is_git_repo"],
        "default_branch": git_ctx.get(
            "default_branch",
            "",
        ),
        "branch_name": "",
        "repo_root": git_ctx.get("repo_root", ""),
        "workspace_dir": str(workspace_dir),
        "max_iterations": max_iterations,
        "current_phase": "prd_generation",
        "session_id": session_id,
        "verify_commands": verify_commands,
    }
    write_loop_config(loop_dir, loop_config)

    logger.info(
        "Mission %s: dir=%s git=%s repo=%s",
        loop_dir.name,
        loop_dir,
        git_ctx["git_installed"],
        git_ctx["is_git_repo"],
    )

    master_prompt = build_master_prompt(
        loop_dir=str(loop_dir),
        agent_id=agent_id,
        max_iterations=max_iterations,
        verify_commands=verify_commands,
        git_context=git_ctx,
        workspace_dir=str(workspace_dir),
    )

    prompt = (
        f"Starting Mission Mode: `{loop_dir.name}`.\n\n"
        f"Task (saved in `{loop_dir}/task.md`):\n"
        f"> {task_text}\n\n"
        f"{master_prompt}\n\n"
        f"**Phase 1 \u2014 Task Decomposition:**\n"
        f"Explore the workspace and generate prd.json.\n"
        f"After writing prd.json, report to the user "
        f"and wait for confirmation. Then update "
        f"`{loop_dir}/loop_config.json` setting "
        f"`current_phase` to `execution_confirmed`."
    )
    return prompt, loop_dir
