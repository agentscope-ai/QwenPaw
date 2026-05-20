# -*- coding: utf-8 -*-
"""Coding Project management endpoints.

Allows users to set, clear, clone, create, and list coding projects
that the Coding Mode IDE operates on.

All endpoints are mounted under ``/workspace/coding-project/``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent_context import get_agent_for_request, get_coding_dir
from ...constant import CODING_PROJECT_SUBDIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace/coding-project", tags=["coding-project"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _projects_base(workspace_dir: Path) -> Path:
    """Return the base directory for all coding projects of this agent."""
    return workspace_dir / CODING_PROJECT_SUBDIR


def _save_project_dir(agent_id: str, project_dir: str | None) -> None:
    """Persist coding_mode.project_dir to agent.json (sync).

    Intended to run inside an executor thread.
    """
    from ...config.config import load_agent_config, save_agent_config

    config = load_agent_config(agent_id)
    config.coding_mode.project_dir = project_dir
    save_agent_config(config.id, config)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SetProjectRequest(BaseModel):
    """Body for PUT /workspace/coding-project."""

    path: str | None = None  # None = reset to default workspace


class CreateProjectRequest(BaseModel):
    name: str


class CloneProjectRequest(BaseModel):
    url: str
    name: str | None = None  # defaults to repo basename


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", summary="Get current coding project directory")
async def get_project(request: Request) -> dict:
    """Return the active coding project path.

    Also indicates whether it differs from the workspace default.
    """
    workspace = await get_agent_for_request(request)
    coding_dir = get_coding_dir(workspace)
    is_workspace = coding_dir.resolve() == workspace.workspace_dir.resolve()
    return {
        "path": str(coding_dir),
        "name": coding_dir.name,
        "is_workspace_default": is_workspace,
        "exists": coding_dir.exists(),
    }


@router.put("", summary="Set (or clear) the active coding project directory")
async def set_project(body: SetProjectRequest, request: Request) -> dict:
    """Set the active coding project directory.

    Pass ``{"path": null}`` to reset to the default workspace directory.
    Pass ``{"path": "/absolute/path"}`` to use that directory.
    """
    workspace = await get_agent_for_request(request)

    if body.path is not None:
        target = Path(body.path).expanduser().resolve()
        # Basic sanity check – dir must exist or we refuse
        if not target.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Path does not exist: {target}",
            )
        if not target.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"Path is not a directory: {target}",
            )
        project_dir: str | None = str(target)
    else:
        project_dir = None  # reset to workspace default

    await asyncio.to_thread(_save_project_dir, workspace.agent_id, project_dir)

    coding_dir = Path(project_dir) if project_dir else workspace.workspace_dir
    return {
        "path": str(coding_dir),
        "name": coding_dir.name,
        "is_workspace_default": project_dir is None,
    }


@router.post("/create", summary="Create a new empty coding project")
async def create_project(body: CreateProjectRequest, request: Request) -> dict:
    """Create a new empty directory and initialise a git repo inside it."""
    name = body.name.strip()
    if not name:
        raise HTTPException(
            status_code=400,
            detail="Project name cannot be empty",
        )

    workspace = await get_agent_for_request(request)
    base = _projects_base(workspace.workspace_dir)

    def _make_dir() -> Path:
        target = (base / name).resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    project_path = await asyncio.to_thread(_make_dir)

    # git init
    proc = await asyncio.create_subprocess_exec(
        "git",
        "init",
        cwd=str(project_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # Set as active project
    await asyncio.to_thread(
        _save_project_dir,
        workspace.agent_id,
        str(project_path),
    )

    return {
        "path": str(project_path),
        "name": project_path.name,
    }


@router.post(
    "/clone",
    summary="Clone a public GitHub/Git repository (SSE progress)",
)
async def clone_project(
    body: CloneProjectRequest,
    request: Request,
) -> StreamingResponse:
    """Clone *url* into the agent's ``coding_projects/`` directory.

    Returns an SSE stream with progress lines and a final ``done`` event.
    Set active project to the cloned directory on success.

    SSE message format::

        data: {"type": "log", "line": "...git output..."}
        data: {"type": "done", "path": "/absolute/path", "name": "repo"}
        data: {"type": "error", "detail": "...error message..."}
    """
    workspace = await get_agent_for_request(request)
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    base = _projects_base(workspace.workspace_dir)
    # Derive repo name from URL when not explicitly provided
    repo_name = (
        body.name.strip() if body.name else url.rstrip("/").split("/")[-1]
    )
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    if not repo_name:
        raise HTTPException(
            status_code=400,
            detail="Cannot derive repo name from URL",
        )

    target = base / repo_name

    agent_id = workspace.agent_id  # capture before entering generator

    async def event_stream():
        try:
            base.mkdir(parents=True, exist_ok=True)

            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--progress",
                url,
                str(target),
                stdout=asyncio.subprocess.PIPE,
                # git writes progress to stderr
                stderr=asyncio.subprocess.STDOUT,
            )

            # Stream output line-by-line
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    payload = json.dumps({"type": "log", "line": line})
                    yield f"data: {payload}\n\n"

            rc = await proc.wait()
            if rc != 0:
                payload = json.dumps(
                    {
                        "type": "error",
                        "detail": f"git clone exited with code {rc}",
                    },
                )
                yield f"data: {payload}\n\n"
                return

            # Set as active project
            await asyncio.to_thread(_save_project_dir, agent_id, str(target))

            payload = json.dumps(
                {"type": "done", "path": str(target), "name": target.name},
            )
            yield f"data: {payload}\n\n"

        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as exc:  # noqa: BLE001
            payload = json.dumps({"type": "error", "detail": str(exc)})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/list", summary="List all coding projects for this agent")
async def list_projects(request: Request) -> list[dict]:
    """Return all subdirectories in the agent's coding_projects folder."""
    workspace = await get_agent_for_request(request)
    base = _projects_base(workspace.workspace_dir)
    current = get_coding_dir(workspace)

    def _scan() -> list[dict]:
        if not base.exists():
            return []
        results = []
        for entry in sorted(base.iterdir()):
            if entry.is_dir():
                is_git = (entry / ".git").exists()
                results.append(
                    {
                        "path": str(entry),
                        "name": entry.name,
                        "is_git": is_git,
                        "is_active": entry.resolve() == current.resolve(),
                    },
                )
        return results

    return await asyncio.to_thread(_scan)


@router.get("/browse", summary="Browse local filesystem directories")
async def browse_fs(
    path: str = "~",
    request: Request = None,  # type: ignore[assignment]
) -> dict:
    """Return directory entries at *path* for use in the folder picker.

    Returns:
        ``{"path": "/abs/path", "entries": [{"name": ..., "is_dir": ...}]}``
    """
    _ = request  # auth side-effect only; value unused

    def _list(dir_path: str) -> dict:
        resolved = Path(dir_path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Not a directory: {resolved}")
        entries = []
        try:
            for entry in sorted(resolved.iterdir()):
                if entry.name.startswith("."):
                    continue
                entries.append(
                    {
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "is_git": entry.is_dir() and (entry / ".git").exists(),
                    },
                )
        except PermissionError:
            pass
        return {
            "path": str(resolved),
            "parent": (
                str(resolved.parent) if resolved.parent != resolved else None
            ),
            "entries": entries,
        }

    try:
        return await asyncio.to_thread(_list, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
