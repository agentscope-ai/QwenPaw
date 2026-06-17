# -*- coding: utf-8 -*-
"""Fork subagent API endpoint.

POST /fork/agent — prepare a forked session + git worktree
for spawn_subagent(fork=True).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...config.config import load_agent_config
from ..runner.session import sanitize_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fork", tags=["fork"])

_WORKTREE_BASE = ".qwenpaw/worktrees"

_LOCALHOST_ADDRS = {"127.0.0.1", "::1", "localhost"}


class ForkAgentRequest(BaseModel):
    agent_id: str
    parent_session_id: str
    user_id: Optional[str] = None
    channel: Optional[str] = None


class ForkAgentResponse(BaseModel):
    fork_session_id: str
    worktree_path: str
    worktree_branch: str


def _enforce_localhost(request: Request) -> None:
    """Reject non-localhost callers."""
    client = request.client
    if client and client.host not in _LOCALHOST_ADDRS:
        raise HTTPException(
            status_code=403,
            detail="Fork endpoint is localhost-only",
        )


def _get_project_dir(agent_id: str) -> Optional[Path]:
    """Resolve the project directory for fork operations.

    Priority:
    1. coding_mode.project_dir (if coding mode is enabled)
    2. workspace_dir (fallback)

    Returns the directory as a Path if it is a git repository,
    or None if no valid git repo is found (in-place fork).
    """
    try:
        config = load_agent_config(agent_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found: {exc}",
        ) from exc

    cm = config.coding_mode
    if cm and cm.enabled and cm.project_dir:
        candidate = Path(cm.project_dir).expanduser().resolve()
    else:
        candidate = Path(config.workspace_dir).expanduser().resolve()

    if not candidate.is_dir():
        return None
    if not (candidate / ".git").exists():
        return None
    return candidate


def _get_sessions_dir(agent_id: str) -> Path:
    """Resolve the sessions directory for the agent."""
    try:
        config = load_agent_config(agent_id)
        workspace = Path(config.workspace_dir).expanduser().resolve()
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot resolve workspace: {exc}",
        ) from exc
    return workspace / "sessions"


def _session_path(
    sessions_dir: Path,
    session_id: str,
    user_id: Optional[str],
    channel: Optional[str],
) -> Path:
    """Reconstruct the session file path (SafeJSONSession compat)."""
    safe_sid = sanitize_filename(session_id)
    safe_uid = sanitize_filename(user_id) if user_id else ""
    filename = (
        f"{safe_uid}_{safe_sid}.json" if safe_uid else f"{safe_sid}.json"
    )

    if channel:
        safe_channel = sanitize_filename(channel)
        return sessions_dir / safe_channel / filename
    return sessions_dir / filename


def _read_session_state(session_file: Path) -> dict:
    """Read full session state dict (SafeJSONSession format).

    The file format is: {"agent": {state_dict}, ...} keyed by
    module name.
    """
    if not session_file.exists():
        return {}
    try:
        data = json.loads(
            session_file.read_text(encoding="utf-8"),
        )
        if isinstance(data, dict):
            return data
        return {}
    except Exception as exc:
        logger.warning(
            "Failed to read session file %s: %s",
            session_file,
            exc,
        )
        return {}


def _write_fork_session(
    sessions_dir: Path,
    fork_session_id: str,
    state: dict,
    user_id: str = "",
    channel: str = "",
) -> None:
    """Write pre-seeded state into a new fork session file.

    Uses the same path convention as SafeJSONSession._get_save_path
    so the runner can load it correctly.
    """
    safe_sid = sanitize_filename(fork_session_id)
    safe_uid = sanitize_filename(user_id) if user_id else ""
    filename = (
        f"{safe_uid}_{safe_sid}.json" if safe_uid else f"{safe_sid}.json"
    )

    if channel:
        safe_channel = sanitize_filename(channel)
        target_dir = sessions_dir / safe_channel
    else:
        target_dir = sessions_dir

    target_dir.mkdir(parents=True, exist_ok=True)
    fork_file = target_dir / filename
    fork_file.write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "Fork session written: %s (%d keys)",
        fork_file,
        len(state),
    )


async def _create_worktree(
    project_dir: Path,
    worktree_id: str,
) -> tuple[Path, str]:
    """Create git worktree at <project_dir>/.qwenpaw/worktrees/<id>.

    Returns (worktree_path, branch_name).
    """
    branch = f"fork/{worktree_id}"
    worktree_path = project_dir / _WORKTREE_BASE / worktree_id
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "git",
        "worktree",
        "add",
        str(worktree_path),
        "-b",
        branch,
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=60,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise HTTPException(
            status_code=500,
            detail="git worktree add timed out (60s)",
        ) from exc
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise HTTPException(
            status_code=500,
            detail=f"git worktree add failed: {detail}",
        )

    logger.info(
        "Created worktree: %s branch=%s",
        worktree_path,
        branch,
    )
    _copy_worktreeinclude_files(project_dir, worktree_path)
    return worktree_path, branch


def _copy_worktreeinclude_files(src: Path, dst: Path) -> None:
    """Copy files listed in .worktreeinclude into the worktree."""
    include_file = src / ".worktreeinclude"
    if not include_file.exists():
        return

    import shutil

    src_resolved = src.resolve()
    dst_resolved = dst.resolve()

    for line in include_file.read_text(
        encoding="utf-8",
    ).splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            logger.warning(
                "Skipping unsafe .worktreeinclude path: %s",
                name,
            )
            continue
        src_file = (src / rel).resolve()
        dst_file = (dst / rel).resolve()
        try:
            src_file.relative_to(src_resolved)
            dst_file.relative_to(dst_resolved)
        except ValueError:
            logger.warning(
                "Skipping worktreeinclude outside project: %s",
                name,
            )
            continue
        if src_file.is_file():
            try:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(dst_file))
            except OSError as exc:
                logger.warning(
                    "Failed to copy %s: %s",
                    src_file,
                    exc,
                )


@router.post("/agent", response_model=ForkAgentResponse)
async def fork_agent(
    req: ForkAgentRequest,
    request: Request,
) -> ForkAgentResponse:
    """Prepare a forked subagent: copy session state + optional worktree.

    This endpoint is internal (localhost-only) and called by
    ``spawn_subagent(fork=True)`` in the tool layer.

    Steps:
    1. Resolve project dir (coding_mode.project_dir or workspace).
    2. Read parent session state.
    3. Write fork session file with inherited state.
    4. If project_dir is a git repo, create worktree.
    5. If worktree created, copy ``.worktreeinclude`` files.
    """
    _enforce_localhost(request)

    project_dir = _get_project_dir(req.agent_id)
    sessions_dir = _get_sessions_dir(req.agent_id)

    parent_file = _session_path(
        sessions_dir,
        req.parent_session_id,
        req.user_id,
        req.channel,
    )
    state = _read_session_state(parent_file)

    fork_id = str(uuid4())[:8]
    fork_session_id = f"sub-{fork_id}"

    _write_fork_session(
        sessions_dir,
        fork_session_id,
        state,
        user_id=req.user_id or "",
        channel=req.channel or "",
    )

    worktree_path = ""
    worktree_branch = ""

    if project_dir is not None:
        wt_path, wt_branch = await _create_worktree(
            project_dir,
            fork_id,
        )
        worktree_path = str(wt_path)
        worktree_branch = wt_branch

    return ForkAgentResponse(
        fork_session_id=fork_session_id,
        worktree_path=worktree_path,
        worktree_branch=worktree_branch,
    )
