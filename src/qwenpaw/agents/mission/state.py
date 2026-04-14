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

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# ── git detection (three-level) ──────────────────────────────────────────


def detect_git_context(workspace_dir: Path) -> dict[str, Any]:
    """Probe the environment for git availability.

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

    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=str(workspace_dir),
            timeout=10,
            check=False,
        )
        if r.returncode != 0:
            return ctx
        ctx["is_git_repo"] = True

        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(workspace_dir),
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            ctx["repo_root"] = r.stdout.strip()

        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(workspace_dir),
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            ctx["current_branch"] = r.stdout.strip()

        for candidate in ("main", "master"):
            r = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{candidate}"],
                capture_output=True,
                text=True,
                cwd=str(workspace_dir),
                timeout=10,
                check=False,
            )
            if r.returncode == 0:
                ctx["default_branch"] = candidate
                break
        if not ctx["default_branch"]:
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


def get_latest_loop_dir(workspace_dir: Path) -> Path | None:
    """Return the most-recently-created mission directory, or None."""
    base = workspace_dir / "missions"
    if not base.exists():
        return None
    dirs = sorted(
        (
            d
            for d in base.iterdir()
            if d.is_dir() and d.name.startswith("mission-")
        ),
        key=lambda d: d.name,
        reverse=True,
    )
    return dirs[0] if dirs else None


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
