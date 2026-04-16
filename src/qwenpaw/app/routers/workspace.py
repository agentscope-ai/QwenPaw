# -*- coding: utf-8 -*-
"""Workspace API – download / upload the entire WORKING_DIR as a zip."""

from __future__ import annotations

import asyncio
import io
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse


router = APIRouter(prefix="/workspace", tags=["workspace"])


def _dir_stats(root: Path) -> tuple[int, int]:
    """Return (file_count, total_size) for *root* recursively."""
    count = 0
    size = 0
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                count += 1
                size += p.stat().st_size
    return count, size


def _zip_directory(root: Path) -> io.BytesIO:
    """Create an in-memory zip archive of *root* and return the buffer.

    All files **and** directories (including empty ones) are included.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(root.rglob("*")):
            arcname = entry.relative_to(root).as_posix()
            if entry.is_file():
                zf.write(entry, arcname)
            elif entry.is_dir():
                # Zip spec: directory entries end with '/'
                zf.write(entry, arcname + "/")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_zip_data(data: bytes, workspace_dir: Path) -> None:
    """Ensure *data* is a valid zip without path-traversal entries."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid zip archive",
        )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            resolved = (workspace_dir / name).resolve()
            if not str(resolved).startswith(str(workspace_dir)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip contains unsafe path: {name}",
                )


def _extract_and_merge_zip(data: bytes, workspace_dir: Path) -> None:
    """Extract zip data and merge into workspace_dir (blocking operation)."""
    tmp_dir = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="qwenpaw_upload_"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp_dir)

        top_entries = list(tmp_dir.iterdir())
        extract_root = tmp_dir
        if len(top_entries) == 1 and top_entries[0].is_dir():
            extract_root = top_entries[0]

        workspace_dir.mkdir(parents=True, exist_ok=True)

        for item in extract_root.iterdir():
            dest = workspace_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists() and dest.is_file():
                    dest.unlink()
                shutil.copytree(item, dest, dirs_exist_ok=True)
    finally:
        if tmp_dir and tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _validate_and_extract_zip(data: bytes, workspace_dir: Path) -> None:
    """Validate and extract zip data (blocking operation)."""
    _validate_zip_data(data, workspace_dir)
    _extract_and_merge_zip(data, workspace_dir)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/download",
    summary="Download workspace as zip",
    description=(
        "Package the entire agent workspace into a zip archive and stream "
        "it back as a downloadable file."
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Zip archive of agent workspace",
        },
    },
)
async def download_workspace(request: Request):
    """Stream agent workspace as a zip file."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    workspace_dir = agent.workspace_dir

    if not workspace_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Workspace does not exist: {workspace_dir}",
        )

    buf = await asyncio.to_thread(_zip_directory, workspace_dir)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"qwenpaw_workspace_{agent.agent_id}_{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post(
    "/upload",
    response_model=dict,
    summary="Upload zip and merge into workspace",
    description=(
        "Upload a zip archive.  Paths present in the zip are merged into "
        "agent workspace (files overwritten, dirs merged).  Paths not in "
        "the zip are left unchanged (e.g. qwenpaw.db, runtime dirs). "
        "Download packs the entire workspace; upload only "
        "overwrites/merges zip contents."
    ),
)
async def upload_workspace(
    request: Request,
    file: UploadFile = File(
        ...,
        description="Zip archive to merge into agent workspace",
    ),
) -> dict:
    """
    Merge uploaded zip contents into agent workspace (overwrite, not clear).
    """
    from ..agent_context import get_agent_for_request

    if file.content_type and file.content_type not in (
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected a zip file, got content-type: {file.content_type}"
            ),
        )

    agent = await get_agent_for_request(request)
    workspace_dir = agent.workspace_dir
    data = await file.read()

    try:
        await asyncio.to_thread(_validate_and_extract_zip, data, workspace_dir)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to merge workspace: {exc}",
        ) from exc
