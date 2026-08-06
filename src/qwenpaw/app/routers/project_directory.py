# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements
"""Project directory management endpoints.

Allows users to set, clear, clone, create, and list project directorys
used by every agent mode.

All endpoints are mounted under ``/workspace/project-directory/``.
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

from ..agent_context import get_agent_for_request, get_agent_project_dir
from ..utils import safe_project_dest
from ...constant import CODING_PROJECT_SUBDIR
from ...utils.command_runner import run_command_async, start_command_async

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspace/project-directory",
    tags=["project-directory"],
)


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
    """Return the base directory for all project directorys of this agent."""
    return workspace_dir / CODING_PROJECT_SUBDIR


def _save_project_dir(agent_id: str, project_dir: str | None) -> None:
    """Persist the agent default project_dir to agent.json.

    Intended to run inside an executor thread.
    """
    from ...config.config import load_agent_config, save_agent_config

    config = load_agent_config(agent_id)
    config.project_dir = project_dir
    save_agent_config(config.id, config)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SetProjectRequest(BaseModel):
    """Body for PUT /workspace/project-directory."""

    path: str | None = None  # None = reset to default workspace


class CreateProjectRequest(BaseModel):
    name: str


class CloneProjectRequest(BaseModel):
    url: str
    name: str | None = None  # defaults to repo basename


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", summary="Get the agent default project directory")
async def get_project(request: Request) -> dict:
    """Return the active project directory path.

    Also indicates whether it differs from the workspace default.
    The ``workspace_dir`` field always contains the agent's default workspace
    directory so callers can display it without a separate request.
    """
    workspace = await get_agent_for_request(request)

    def _snapshot() -> dict:
        coding_dir = get_agent_project_dir(workspace)
        workspace_dir = workspace.workspace_dir
        is_workspace = coding_dir.resolve() == workspace_dir.resolve()
        return {
            "path": str(coding_dir),
            "name": coding_dir.name,
            "is_workspace_default": is_workspace,
            "workspace_dir": str(workspace_dir),
            "exists": coding_dir.exists(),
        }

    return await asyncio.to_thread(_snapshot)


@router.put(
    "",
    summary="Set (or clear) the active project directory directory",
)
async def set_project(body: SetProjectRequest, request: Request) -> dict:
    """Set the active project directory directory.

    Pass ``{"path": null}`` to reset to the default workspace directory.
    Pass ``{"path": "/absolute/path"}`` to use that directory.
    """
    workspace = await get_agent_for_request(request)

    def _resolve_target() -> str | None:
        if body.path is None:
            return None
        target = Path(body.path).expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        return str(target)

    try:
        project_dir = await asyncio.to_thread(_resolve_target)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Path does not exist: {exc}",
        ) from exc
    except NotADirectoryError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Path is not a directory: {exc}",
        ) from exc

    await asyncio.to_thread(_save_project_dir, workspace.agent_id, project_dir)

    coding_dir = Path(project_dir) if project_dir else workspace.workspace_dir
    return {
        "path": str(coding_dir),
        "name": coding_dir.name,
        "is_workspace_default": project_dir is None,
    }


@router.post("/create", summary="Create a new empty project directory")
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


# Import-specific sensitive directory names (case-insensitive).
# Checked against every path component and every entry during
# copy so that ``~/backup/.ssh`` is caught regardless of where
# it appears.  Intentionally separate from sandbox deny-list
# because security semantics differ: sandbox controls runtime
# permissions; this list prevents data exfiltration via import.
_SENSITIVE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".ssh",
        ".aws",
        ".gnupg",
        ".kube",
        ".docker",
        ".azure",
        ".claude",
        ".password-store",
    },
)

# Sensitive file basenames (case-insensitive).  Skipped during
# copy so files like ``.netrc`` inside a project are never
# exfiltrated.
_SENSITIVE_FILE_NAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        ".yarnrc",
        ".pypirc",
        ".gitconfig",
        ".git-credentials",
        ".terraformrc",
        ".vault-token",
    },
)

# Multi-component sensitive directory sequences (lowercase).
# Matched anywhere in the path using a sliding window so that
# ``~/backup/.config/gh`` is caught even though the source is
# ``~/backup``.
_SENSITIVE_DIR_SEQUENCES: tuple[tuple[str, ...], ...] = (
    (".config", "gcloud"),
    (".config", "nix"),
    (".config", "gh"),
    # macOS paths
    ("library", "keychains"),
    ("library", "cookies"),
    ("library", "application support", "google", "chrome"),
    ("library", "application support", "firefox"),
    # Windows AppData paths (also covers WSL mounts)
    ("appdata", "roaming", "gcloud"),
    ("appdata", "roaming", "github cli"),
    ("appdata", "local", "google", "chrome", "user data"),
    ("appdata", "roaming", "mozilla", "firefox"),
)


def _match_dir_sequence(
    parts: tuple[str, ...],
    seq: tuple[str, ...],
) -> bool:
    """Check if *seq* appears as a contiguous subsequence in *parts*.

    Both *parts* and *seq* must already be lowercased.
    """
    seq_len = len(seq)
    for i in range(len(parts) - seq_len + 1):
        if parts[i : i + seq_len] == seq:
            return True
    return False


def _is_sensitive_name(name: str) -> bool:
    """Check if a single path component is a sensitive name."""
    low = name.lower()
    return low in _SENSITIVE_DIR_NAMES or low in _SENSITIVE_FILE_NAMES


def _validate_import_source(source: Path) -> None:
    """Reject source paths outside home or inside sensitive dirs.

    Raises HTTPException(403) when:
    - *source* is not under the user's home directory.
    - *source* equals the home directory itself.
    - *source* path contains a sensitive component name.
    - *source* path contains a sensitive directory sequence.
    """
    home = Path.home().resolve()
    if not source.is_relative_to(home):
        raise HTTPException(
            status_code=403,
            detail=f"Source must be under home directory: {home}",
        )

    if source == home:
        raise HTTPException(
            status_code=403,
            detail="Cannot import the entire home directory",
        )

    rel = source.relative_to(home)

    for part in rel.parts:
        if _is_sensitive_name(part):
            raise HTTPException(
                status_code=403,
                detail=f"Path contains sensitive " f"component: {part}",
            )

    low_parts = tuple(p.lower() for p in rel.parts)
    for seq in _SENSITIVE_DIR_SEQUENCES:
        if _match_dir_sequence(low_parts, seq):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Path contains sensitive directory "
                    f"sequence: {'/'.join(seq)}"
                ),
            )


@router.post(
    "/import-local",
    summary="Copy a local directory into project directorys",
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

    _validate_import_source(source)

    dest_name = body.name.strip() if body.name else source.name
    base = _projects_base(workspace.workspace_dir)
    dest = safe_project_dest(base, dest_name)

    excluded_sensitive: list[str] = []

    def _copy() -> Path:
        import shutil
        import stat

        _pattern_ignore = shutil.ignore_patterns(
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

        def _is_link_or_junction(p: Path) -> bool:
            """Detect symlinks and Windows junctions."""
            if p.is_symlink():
                return True
            if sys.platform == "win32":
                try:
                    st = p.lstat()
                    attrs = getattr(
                        st,
                        "st_file_attributes",
                        0,
                    )
                    reparse = getattr(
                        stat,
                        "FILE_ATTRIBUTE_REPARSE_POINT",
                        0x400,
                    )
                    if attrs & reparse:
                        return True
                except OSError:
                    pass
            return False

        def _dir_parts_lower(dirpath: str) -> tuple[str, ...]:
            """Return lowercased path components of *dirpath*."""
            return tuple(p.lower() for p in Path(dirpath).parts)

        def _ignore(directory, contents):
            """Skip artifacts, symlinks, sensitive entries.

            Apply security checks during the copy walk instead of
            performing a separate pre-scan.
            """
            ignored = _pattern_ignore(directory, contents)
            d = Path(directory)
            # Skip symlinks and Windows junctions.
            ignored |= {c for c in contents if _is_link_or_junction(d / c)}
            # Skip sensitive directory and file names.
            sensitive_hits = {
                c
                for c in contents
                if c.lower() in _SENSITIVE_DIR_NAMES
                or c.lower() in _SENSITIVE_FILE_NAMES
            }
            ignored |= sensitive_hits
            # Skip entries that complete a sensitive
            # multi-component directory sequence.
            dir_low = _dir_parts_lower(directory)
            for c in contents:
                if c in ignored:
                    continue
                full = dir_low + (c.lower(),)
                for seq in _SENSITIVE_DIR_SEQUENCES:
                    if _match_dir_sequence(full, seq):
                        ignored.add(c)
                        sensitive_hits.add(c)
                        break
            # Record excluded sensitive entries with relative path.
            if sensitive_hits:
                rel_dir = Path(directory).relative_to(source)
                for name in sorted(sensitive_hits):
                    excluded_sensitive.append(
                        str(rel_dir / name) if str(rel_dir) != "." else name,
                    )
            return ignored

        base.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            str(source),
            str(dest),
            ignore=_ignore,
            dirs_exist_ok=True,
        )
        return dest

    try:
        project_path = await asyncio.to_thread(_copy)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if excluded_sensitive:
        excluded_sensitive = sorted(set(excluded_sensitive))
        logger.info(
            "import-local excluded sensitive entries: %s",
            ", ".join(excluded_sensitive),
        )

    await asyncio.to_thread(
        _save_project_dir,
        workspace.agent_id,
        str(project_path),
    )

    result: dict = {
        "path": str(project_path),
        "name": project_path.name,
    }
    if excluded_sensitive:
        result["excluded"] = excluded_sensitive
    return result


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


@router.get("/list", summary="List all project directorys for this agent")
async def list_projects(request: Request) -> list[dict]:
    """Return all subdirectories in the agent's coding_projects folder."""
    workspace = await get_agent_for_request(request)
    base = _projects_base(workspace.workspace_dir)

    def _scan() -> list[dict]:
        current = get_agent_project_dir(workspace)
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
