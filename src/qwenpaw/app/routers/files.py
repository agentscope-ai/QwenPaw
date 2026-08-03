# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.responses import FileResponse

from qwenpaw.constant import WORKING_DIR
from qwenpaw.security.tool_guard.guardians.file_guardian import (
    FilePathToolGuardian,
    _normalize_path,
)

from ..utils import check_upload_size, safe_join

router = APIRouter(prefix="/files", tags=["files"])

_ALLOWED_ROOT: Path = WORKING_DIR.resolve()

# Reuse the FileGuard sensitive path detection for the preview endpoint.
_file_guardian = FilePathToolGuardian()


def _is_preview_outside_workspace_allowed() -> bool:
    """Check ``security.file_guard.allow_preview_outside_workspace``."""
    try:
        from qwenpaw.config import load_config

        return bool(
            load_config().security.file_guard.allow_preview_outside_workspace,
        )
    except Exception:
        return False


def _check_path(path: Path, for_write: bool = False) -> str | None:
    """Return ``None`` when *path* is allowed, or an error reason string.

    When ``allow_preview_outside_workspace`` is enabled, skip the
    WORKING_DIR containment check so that console can preview files
    (e.g. media produced by tools) stored outside the workspace.
    Write operations (``for_write=True``) always stay inside WORKING_DIR.
    The sensitive-file guard is **always** enforced.
    """
    resolved = path.resolve()
    # 1. Must not be a FileGuard-sensitive path.
    normalized = _normalize_path(str(resolved))
    # pylint: disable-next=protected-access
    if _file_guardian._is_sensitive(normalized):
        return "SENSITIVE_FILE_BLOCKED"
    # 2. Workspace scope check (skippable via config for reads only).
    if for_write or not _is_preview_outside_workspace_allowed():
        if not (
            resolved == _ALLOWED_ROOT or resolved.is_relative_to(_ALLOWED_ROOT)
        ):
            return "OUTSIDE_WORKSPACE"
    return None


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file",
)
async def preview_file(
    filepath: str,
):
    """Preview file."""
    normalized = unquote(filepath)

    # Normalize /C:/... to C:/... on Windows.
    if (
        len(normalized) >= 4
        and normalized[0] == "/"
        and normalized[2] == ":"
        and normalized[1].isalpha()
    ):
        normalized = normalized[1:]

    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = Path("/" + normalized)
    path = path.resolve()
    reason = _check_path(path)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    if not os.access(path, os.R_OK):
        raise HTTPException(status_code=500, detail="Permission denied")
    return FileResponse(path, filename=path.name)


def _resolve_workspace_path(raw: str, for_write: bool) -> Path:
    """Normalize *raw* to an absolute path and validate it.

    Raises HTTPException for invalid / disallowed paths.
    """
    normalized = unquote(raw)
    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = _ALLOWED_ROOT / path
    path = path.resolve()
    reason = _check_path(path, for_write=for_write)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    return path


def _entry_info(path: Path) -> dict:
    st = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "size": st.st_size if path.is_file() else 0,
        "modified_time": st.st_mtime,
    }


@router.get(
    "/list",
    summary="List directory contents",
    description=(
        "List the contents of *path* (relative to WORKING_DIR, or absolute). "
        "Omit *path* to list the WORKING_DIR root."
    ),
)
async def list_directory(path: str | None = None) -> list[dict]:
    """List directory contents."""
    if path is None:
        target = _ALLOWED_ROOT
        reason = _check_path(target, for_write=False)
        if reason:
            raise HTTPException(status_code=403, detail=reason)
    else:
        target = _resolve_workspace_path(path, for_write=False)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Not found")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
        try:
            if _check_path(child, for_write=False):
                continue
            entries.append(_entry_info(child))
        except OSError:
            continue
    return entries


@router.get(
    "/download/{path:path}",
    summary="Download a single file",
    description="Download *path* (relative to WORKING_DIR) as an attachment.",
)
async def download_file(path: str) -> FileResponse:
    """Download a single file."""
    target = _resolve_workspace_path(path, for_write=False)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target, filename=target.name)


class MkdirRequest(BaseModel):
    path: str = Field(..., description="Directory path in WORKING_DIR")


@router.post(
    "/mkdir",
    summary="Create a directory",
    description="Create *path* (relative to WORKING_DIR). Creates parents.",
)
async def create_directory(body: MkdirRequest) -> dict:
    """Create a directory (and parents)."""
    target = _resolve_workspace_path(body.path, for_write=True)
    if target == _ALLOWED_ROOT:
        raise HTTPException(status_code=400, detail="Cannot operate on root")
    if target.exists():
        raise HTTPException(status_code=409, detail="Target exists")
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Target exists") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"created": str(target)}


@router.delete(
    "/delete/{path:path}",
    summary="Delete a file or directory",
    description=(
        "Delete *path* (relative to WORKING_DIR). Directories require "
        "recursive=true to delete non-empty contents."
    ),
)
async def delete_path(
    path: str,
    recursive: bool = False,
) -> dict:
    """Delete a file or directory."""
    target = _resolve_workspace_path(path, for_write=True)
    if target == _ALLOWED_ROOT:
        raise HTTPException(status_code=400, detail="Cannot operate on root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_dir():
        if not recursive and any(target.iterdir()):
            raise HTTPException(status_code=409, detail="Directory not empty")
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": str(target)}


class RenameRequest(BaseModel):
    source: str = Field(..., description="Source path relative to WORKING_DIR")
    target: str = Field(..., description="Target path relative to WORKING_DIR")


@router.post(
    "/rename",
    summary="Rename or move a file/directory",
    description="Rename/move *source* to *target* (relative to WORKING_DIR).",
)
async def rename_path(body: RenameRequest) -> dict:
    """Rename or move a file/directory."""
    src = _resolve_workspace_path(body.source, for_write=True)
    if src == _ALLOWED_ROOT:
        raise HTTPException(status_code=400, detail="Cannot operate on root")
    dst = _resolve_workspace_path(body.target, for_write=True)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if dst.exists():
        raise HTTPException(status_code=409, detail="Target exists")
    try:
        src.rename(dst)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"renamed": str(src), "to": str(dst)}


@router.post(
    "/upload",
    summary="Upload a single file",
    description=(
        "Upload a file to *path* (directory relative to WORKING_DIR, "
        "defaults to root). Filename is rejected against traversal."
    ),
)
async def upload_file(
    file: UploadFile = File(..., description="File to upload"),
    path: str | None = None,
) -> dict:
    """Upload a single file into WORKING_DIR."""
    data = await file.read()
    check_upload_size(data)
    if path:
        target_dir = _resolve_workspace_path(path, for_write=True)
        if not target_dir.is_dir():
            raise HTTPException(status_code=404, detail="Not found")
    else:
        target_dir = _ALLOWED_ROOT
    raw_name = file.filename or "upload"
    safe_name = Path(raw_name).name
    if safe_name != raw_name:
        # Filename contained path separators / ".." — reject rather than
        # silently dropping the directory portion.
        raise HTTPException(status_code=400, detail="Traversal not allowed")
    target = safe_join(target_dir, safe_name)
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"uploaded": str(target)}
