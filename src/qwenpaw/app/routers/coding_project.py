# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements
"""Coding Project management endpoints.

Allows users to set, clear, clone, create, and list coding projects
that the Coding Mode IDE operates on.

All endpoints are mounted under ``/workspace/coding-project/``.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent_context import get_agent_for_request, get_coding_dir
from ..utils import safe_project_dest
from ...constant import CODING_PROJECT_SUBDIR
from ...utils.command_runner import run_command_async, start_command_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace/coding-project", tags=["coding-project"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_windows_drives_response() -> dict:
    """Return a browse-dirs response listing drives."""
    import ctypes

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    dirs: list[dict] = []
    for i in range(26):
        if bitmask & (1 << i):
            letter = chr(ord("A") + i)
            dirs.append(
                {
                    "name": f"{letter}:",
                    "path": f"{letter}:\\",
                },
            )
    return {
        "current": "/",
        "parent": None,
        "dirs": dirs,
        "selectable": False,
    }


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
    The ``workspace_dir`` field always contains the agent's default workspace
    directory so callers can display it without a separate request.
    """
    workspace = await get_agent_for_request(request)
    coding_dir = get_coding_dir(workspace)
    workspace_dir = workspace.workspace_dir
    is_workspace = coding_dir.resolve() == workspace_dir.resolve()
    return {
        "path": str(coding_dir),
        "name": coding_dir.name,
        "is_workspace_default": is_workspace,
        "workspace_dir": str(workspace_dir),
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
    target = safe_project_dest(base, name)

    def _make_dir() -> Path:
        target.mkdir(parents=True, exist_ok=True)
        return target

    project_path = await asyncio.to_thread(_make_dir)

    await run_command_async(
        ["git", "init"],
        cwd=str(project_path),
        check=False,
        timeout=None,
    )

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

    target = safe_project_dest(base, repo_name)

    agent_id = workspace.agent_id  # capture before entering generator

    async def event_stream():
        try:
            base.mkdir(parents=True, exist_ok=True)

            proc = await start_command_async(
                ["git", "clone", "--progress", url, str(target)],
                stdout=asyncio.subprocess.PIPE,
                # git writes progress to stderr
                stderr=asyncio.subprocess.STDOUT,
            )

            assert proc.stdout is not None
            buf = ""  # raw read: \r progress arrives real-time
            while True:
                raw = await proc.stdout.read(4096)
                if not raw:
                    break
                buf += raw.decode("utf-8", errors="replace")
                # Split on \r or \n (or \r\n)
                while True:
                    idx = -1
                    for sep in ("\r\n", "\r", "\n"):
                        pos = buf.find(sep)
                        if pos != -1 and (idx == -1 or pos < idx):
                            idx = pos
                            sep_len = len(sep)
                    if idx == -1:
                        break
                    line = buf[:idx].strip()
                    buf = buf[idx + sep_len :]
                    if line:
                        payload = json.dumps(
                            {"type": "log", "line": line},
                        )
                        yield f"data: {payload}\n\n"
            # Flush remaining buffer
            remaining = buf.strip()
            if remaining:
                payload = json.dumps(
                    {"type": "log", "line": remaining},
                )
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
        except Exception as exc:
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


class ImportLocalRequest(BaseModel):
    path: str
    name: str | None = None  # override destination folder name


@router.post(
    "/import-local",
    summary="Copy a local directory into coding projects",
)
async def import_local(body: ImportLocalRequest, request: Request) -> dict:
    """Copy *path* into the agent's ``coding_projects/`` directory.

    Common build artifacts (``node_modules``, ``dist``, etc.) are excluded
    to avoid copying large generated directories.  ``.git`` is preserved so
    the existing history is available in the copy.
    """
    workspace = await get_agent_for_request(request)
    source = await asyncio.to_thread(
        lambda: Path(body.path).expanduser().resolve(),
    )

    if not source.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Path does not exist: {source}",
        )
    if not source.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Not a directory: {source}",
        )

    dest_name = body.name.strip() if body.name else source.name
    base = _projects_base(workspace.workspace_dir)
    dest = safe_project_dest(base, dest_name)

    def _copy() -> Path:
        import shutil

        base.mkdir(parents=True, exist_ok=True)
        ignore = shutil.ignore_patterns(
            "node_modules",
            ".next",
            "dist",
            "build",
            "__pycache__",
            ".cache",
            ".venv",
            "venv",
            "*.egg-info",
            ".mypy_cache",
            ".tox",
        )
        shutil.copytree(
            str(source),
            str(dest),
            ignore=ignore,
            dirs_exist_ok=True,
        )
        return dest

    try:
        project_path = await asyncio.to_thread(_copy)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
    "/upload-zip",
    summary="Upload a zip of a project folder to coding_projects/",
)
async def upload_zip(
    request: Request,
    name: str = Query(
        ...,
        description="Destination folder name inside coding_projects/",
    ),
    file: UploadFile = File(
        ...,
        description="Zip archive of the project folder",
    ),
) -> dict:
    """Extract *file* (zip) into ``coding_projects/<name>/`` and activate it.

    The endpoint guards against zip-slip by validating each member path before
    extraction.
    """
    workspace = await get_agent_for_request(request)
    base = _projects_base(workspace.workspace_dir)
    dest = safe_project_dest(base, name)

    content = await file.read()

    def _extract() -> Path:
        base.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=True)
        dest_resolved = dest.resolve()
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for member in zf.namelist():
                if Path(member).is_absolute():
                    raise ValueError(
                        f"Absolute path in zip not allowed: {member}",
                    )
                member_path = (dest_resolved / member).resolve()
                try:
                    member_path.relative_to(dest_resolved)
                except ValueError as exc:
                    raise ValueError(
                        f"Zip slip detected for member: {member}",
                    ) from exc
            zf.extractall(str(dest))
        return dest

    try:
        project_path = await asyncio.to_thread(_extract)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Auto-init git repo if the extracted folder has no repo
    from ..routers.git import _auto_init_repo, _resolve_branch

    _, needs_init = await _resolve_branch(project_path)
    if needs_init:
        await _auto_init_repo(project_path)

    await asyncio.to_thread(
        _save_project_dir,
        workspace.agent_id,
        str(project_path),
    )
    return {"path": str(project_path), "name": project_path.name}


@router.get(
    "/browse-dirs",
    summary="Browse directories on the server for project selection",
)
async def browse_dirs(
    path: str = Query(
        default="~",
        description="Directory to list (default: home)",
    ),
    show_hidden: bool = Query(
        default=False,
        description="Include hidden directories",
    ),
) -> dict:
    """Return subdirectories at *path* for the file browser UI.

    On Windows, ``"/"`` is treated as a virtual root that
    lists all available drive letters (C:, D:, ...).
    """
    # Windows virtual root: list all drive letters
    if sys.platform == "win32" and path in ("/", "\\"):
        return await asyncio.to_thread(
            _list_windows_drives_response,
        )

    target = await asyncio.to_thread(
        lambda: Path(path).expanduser().resolve(),
    )

    if not target.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Path does not exist: {target}",
        )
    if not target.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Not a directory: {target}",
        )

    def _scan() -> dict:
        dirs: list[dict] = []
        try:
            for entry in sorted(target.iterdir()):
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        dirs.append(
                            {
                                "name": entry.name,
                                "path": str(entry),
                            },
                        )
                except (PermissionError, OSError):
                    continue
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {target}",
            ) from exc
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Path does not exist: {target}",
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list directory: {target}",
            ) from exc
        parent = target.parent
        # On Windows drive root, parent points to
        # the virtual drives listing.
        if sys.platform == "win32" and parent == target:
            parent_str: str | None = "/"
        else:
            parent_str = str(parent) if parent != target else None
        return {
            "current": str(target),
            "parent": parent_str,
            "dirs": dirs,
        }

    return await asyncio.to_thread(_scan)


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
