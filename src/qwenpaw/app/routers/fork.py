# -*- coding: utf-8 -*-
"""Fork subagent API endpoint.

POST /fork/agent — prepare a forked session + git worktree
for spawn_subagent(fork=True).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...config.config import load_agent_config
from ...utils.io_utils import run_sync_io

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
    1. Agent project_dir
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

    if config.project_dir:
        candidate = Path(config.project_dir).expanduser().resolve()
    else:
        candidate = Path(config.workspace_dir).expanduser().resolve()

    if not candidate.is_dir():
        return None
    if not (candidate / ".git").exists():
        return None
    return candidate


async def _get_workspace(request: Request, agent_id: str):
    """Return the live workspace that owns the session database."""
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    try:
        workspace = await manager.get_agent(agent_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found: {exc}",
        ) from exc
    if workspace.session is None or workspace.transcript_store is None:
        raise HTTPException(
            status_code=503,
            detail="Agent session storage is not available",
        )
    return workspace


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

    The fork inherits completed transcript messages and persisted agent
    context. Process-local mode state is intentionally not copied.
    """
    _enforce_localhost(request)

    project_dir = _get_project_dir(req.agent_id)
    workspace = await _get_workspace(request, req.agent_id)
    user_id = req.user_id or ""
    channel = req.channel or ""

    # Import a legacy parent on first access before cloning from the DB.
    await workspace.session.get_session_state_dict(
        req.parent_session_id,
        user_id,
        channel,
    )

    fork_id = str(uuid4())[:8]
    fork_session_id = f"sub-{fork_id}"

    cloned = await run_sync_io(
        workspace.transcript_store.clone_session,
        source_session_id=req.parent_session_id,
        source_user_id=user_id,
        source_channel=channel,
        target_session_id=fork_session_id,
        target_user_id=user_id,
        target_channel=channel,
    )
    if not cloned:
        await run_sync_io(
            workspace.transcript_store.write_runtime_state,
            session_id=fork_session_id,
            user_id=user_id,
            channel=channel,
            state={},
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
