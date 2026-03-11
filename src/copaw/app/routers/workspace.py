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

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from ...constant import WORKING_DIR

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


def _validate_zip_data(data: bytes) -> None:
    """Ensure *data* is a valid zip without path-traversal entries."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid zip archive",
        )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            resolved = (WORKING_DIR / name).resolve()
            if not str(resolved).startswith(str(WORKING_DIR)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip contains unsafe path: {name}",
                )


def _extract_and_merge_zip(data: bytes) -> None:
    """Extract zip data and merge into WORKING_DIR (blocking operation)."""
    tmp_dir = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="copaw_upload_"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp_dir)

        top_entries = list(tmp_dir.iterdir())
        extract_root = tmp_dir
        if len(top_entries) == 1 and top_entries[0].is_dir():
            extract_root = top_entries[0]

        WORKING_DIR.mkdir(parents=True, exist_ok=True)

        for item in extract_root.iterdir():
            dest = WORKING_DIR / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists() and dest.is_file():
                    dest.unlink()
                shutil.copytree(item, dest, dirs_exist_ok=True)
    finally:
        if tmp_dir and tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _validate_and_extract_zip(data: bytes) -> None:
    """Validate and extract zip data (blocking operation)."""
    _validate_zip_data(data)
    _extract_and_merge_zip(data)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/download",
    summary="Download workspace as zip",
    description=(
        "Package the entire WORKING_DIR into a zip archive and stream it "
        "back as a downloadable file."
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Zip archive of WORKING_DIR",
        },
    },
)
async def download_workspace():
    """Stream WORKING_DIR as a zip file."""
    if not WORKING_DIR.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"WORKING_DIR does not exist: {WORKING_DIR}",
        )

    buf = await asyncio.to_thread(_zip_directory, WORKING_DIR)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"copaw_workspace_{timestamp}.zip"

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
        "WORKING_DIR (files overwritten, dirs merged).  Paths not in the zip "
        "are left unchanged (e.g. copaw.db, runtime dirs).  Download packs "
        "the entire WORKING_DIR; upload only overwrites/merges zip contents."
    ),
)
async def upload_workspace(
    file: UploadFile = File(
        ...,
        description="Zip archive to merge into WORKING_DIR",
    ),
) -> dict:
    """
    Merge uploaded zip contents into WORKING_DIR (overwrite, do not clear).
    """
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

    data = await file.read()

    try:
        await asyncio.to_thread(_validate_and_extract_zip, data)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to merge workspace: {exc}",
        ) from exc
