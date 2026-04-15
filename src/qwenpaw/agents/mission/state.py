# -*- coding: utf-8 -*-
"""Mission Mode state-file management.

State file layout follows the snarktank/ralph convention:

    {workspace_dir}/missions/{loop_id}/
    ├── loop_config.json  # environment metadata (git, paths)
    ├── prd.json          # task list (worker updates ``passes``)
    ├── progress.txt      # append-only iteration log
    └── task.md           # original task description (read-only)

Each loop_dir IS the working directory for that loop — fully isolated
from other loops and the shared agent workspace.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# ── git detection (three-level) ──────────────────────────────────────────


async def _git_cmd(
    *args: str,
    cwd: str,
) -> tuple[int, str]:
    """Run a git sub-command asynchronously, return (returncode, stdout)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return proc.returncode or 0, stdout.decode().strip()
    except (asyncio.TimeoutError, OSError):
        return 1, ""


async def detect_git_context(workspace_dir: Path) -> dict[str, Any]:
    """Probe the environment for git availability (async).

    Returns a dict with keys::

        git_installed   – bool, ``git`` binary found on PATH
        is_git_repo     – bool, *workspace_dir* is inside a git repo
        default_branch  – str, e.g. ``"main"``
        current_branch  – str
        repo_root       – str, absolute path of the repo root
    """
    ctx: dict[str, Any] = {
        "git_installed": False,
        "is_git_repo": False,
        "default_branch": "",
        "current_branch": "",
        "repo_root": "",
    }

    if shutil.which("git") is None:
        return ctx
    ctx["git_installed"] = True

    cwd = str(workspace_dir)

    try:
        rc, _ = await _git_cmd("rev-parse", "--is-inside-work-tree", cwd=cwd)
        if rc != 0:
            return ctx
        ctx["is_git_repo"] = True

        # Run remaining queries concurrently
        toplevel_task = _git_cmd("rev-parse", "--show-toplevel", cwd=cwd)
        branch_task = _git_cmd("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
        main_task = _git_cmd(
            "rev-parse",
            "--verify",
            "refs/heads/main",
            cwd=cwd,
        )
        master_task = _git_cmd(
            "rev-parse",
            "--verify",
            "refs/heads/master",
            cwd=cwd,
        )

        (
            (rc_top, out_top),
            (rc_br, out_br),
            (rc_main, _),
            (rc_master, _),
        ) = await asyncio.gather(
            toplevel_task,
            branch_task,
            main_task,
            master_task,
        )

        if rc_top == 0:
            ctx["repo_root"] = out_top
        if rc_br == 0:
            ctx["current_branch"] = out_br
        if rc_main == 0:
            ctx["default_branch"] = "main"
        elif rc_master == 0:
            ctx["default_branch"] = "master"
        else:
            ctx["default_branch"] = ctx["current_branch"]
    except Exception:
        logger.debug("git detection failed", exc_info=True)
    return ctx


# ── loop directory & state files ─────────────────────────────────────────


def create_loop_dir(workspace_dir: Path) -> Path:
    """Create a new mission directory and return its path."""
    loop_id = f"mission-{_ts()}"
    loop_dir = workspace_dir / "missions" / loop_id
    loop_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Created mission dir: %s", loop_dir)
    return loop_dir


def write_loop_config(loop_dir: Path, config: dict[str, Any]) -> Path:
    """Persist environment metadata for this loop."""
    p = loop_dir / "loop_config.json"
    p.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def read_loop_config(loop_dir: Path) -> dict[str, Any]:
    """Read the loop_config.json, returning empty dict if missing."""
    p = loop_dir / "loop_config.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def write_task_md(loop_dir: Path, task_text: str) -> Path:
    """Persist the original task description."""
    p = loop_dir / "task.md"
    p.write_text(task_text, encoding="utf-8")
    return p


def write_prd_json(loop_dir: Path, prd: dict[str, Any]) -> Path:
    """Write the structured task list."""
    p = loop_dir / "prd.json"
    p.write_text(
        json.dumps(prd, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def init_progress_txt(loop_dir: Path) -> Path:
    """Create initial progress log with empty Codebase Patterns."""
    p = loop_dir / "progress.txt"
    p.write_text(
        "## Codebase Patterns\n"
        "(none yet — add reusable patterns here as you discover them)\n"
        "---\n",
        encoding="utf-8",
    )
    return p


def read_prd(loop_dir: Path) -> dict[str, Any]:
    """Read and return the prd.json contents."""
    p = loop_dir / "prd.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def get_all_passed(prd: dict[str, Any]) -> bool:
    """Check whether every story in the PRD has ``passes: true``."""
    stories = prd.get("userStories", [])
    if not stories:
        return False
    return all(s.get("passes") for s in stories)


def get_active_loop_dir(
    workspace_dir: Path,
    session_id: str = "",
) -> Path | None:
    """Return the most recent mission directory for this session.

    Scans recent mission directories and returns the newest one whose
    loop_config.json.session_id matches the provided session_id.

    Args:
        workspace_dir: Workspace root directory.
        session_id: Current session ID. If empty, returns the globally
            latest loop (backward compatibility).

    Returns:
        Path to the newest loop matching session_id, or None if not found.
    """
    base = workspace_dir / "missions"
    if not base.exists():
        return None

    # Get all mission dirs sorted by creation time (newest first)
    dirs = sorted(
        (
            d
            for d in base.iterdir()
            if d.is_dir() and d.name.startswith("mission-")
        ),
        key=lambda d: d.name,
        reverse=True,
    )

    # If no session_id, return the globally latest (backward compat)
    if not session_id:
        return dirs[0] if dirs else None

    # Scan recent loops (limit to 20 to avoid perf issues)
    for loop_dir in dirs[:20]:
        cfg = read_loop_config(loop_dir)
        loop_session = cfg.get("session_id", "")
        if loop_session == session_id:
            return loop_dir

    return None


def list_loop_dirs(workspace_dir: Path) -> list[dict[str, Any]]:
    """Return summary info for all missions in a workspace."""
    base = workspace_dir / "missions"
    if not base.exists():
        return []
    result = []
    for d in sorted(base.iterdir(), reverse=True):
        if not d.is_dir() or not d.name.startswith("mission-"):
            continue
        prd = read_prd(d)
        cfg = read_loop_config(d)
        stories = prd.get("userStories", [])
        passed = sum(1 for s in stories if s.get("passes"))
        result.append(
            {
                "loop_id": d.name,
                "path": str(d),
                "project": prd.get("project", ""),
                "description": prd.get("description", ""),
                "stories_total": len(stories),
                "stories_passed": passed,
                "all_passed": passed == len(stories) and len(stories) > 0,
                "branch": cfg.get("branch_name", ""),
                "git_installed": cfg.get("git_installed", False),
                "is_git_repo": cfg.get("is_git_repo", False),
            },
        )
    return result
