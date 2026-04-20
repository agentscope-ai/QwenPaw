# -*- coding: utf-8 -*-
"""Backup API – create, list, restore, delete, export, import."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ...backup import (
    create_stream,
    delete_backups,
    execute_restore,
    export_backup,
    get_backup,
    import_backup,
    list_backups,
)
from ...backup.models import (
    BackupConflictError,
    BackupDetail,
    BackupMeta,
    CreateBackupRequest,
    DeleteBackupsRequest,
    DeleteBackupsResponse,
    RestoreBackupRequest,
)
from ...constant import BACKUP_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backups", tags=["backups"])

_UPLOAD_TMP_MAX_AGE = 3600  # 1 hour


def _cleanup_stale_uploads() -> None:
    """Remove stale temp files in BACKUP_DIR older than _UPLOAD_TMP_MAX_AGE.

    Cleans two kinds of temp files:
    * ``*.upload_tmp`` – partial uploads kept for conflict-resolution tokens.
      Only files older than the max-age cutoff are removed so that a live
      pending_token upload is not accidentally deleted.
    * ``*.tmp`` – in-progress backup creation files left by a crashed process.
      These are never accessed again after the process exits, so any file
      older than the cutoff is safe to remove.
    """
    if not BACKUP_DIR.is_dir():
        return
    cutoff = time.time() - _UPLOAD_TMP_MAX_AGE
    for pattern in ("*.upload_tmp", "*.tmp"):
        for f in BACKUP_DIR.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/stream", summary="Create backup with SSE progress stream")
async def create_backup_stream(req: CreateBackupRequest):
    """Create a backup and stream progress via SSE.

    When the client disconnects the background thread stops at the next agent
    boundary without writing the final file. Each event is formatted as
    `data: <json>\\n\\n`; see create_stream for event shapes.
    """

    async def generate():
        try:
            async for event in create_stream(req):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        # Disable proxy/nginx buffering so events reach the client immediately
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", response_model=list[BackupMeta], summary="List backups")
async def list_backups_route():
    return await list_backups()


# Fixed-path routes MUST be registered before /{backup_id} to avoid
# FastAPI treating "delete" / "import" as a backup_id.


@router.post(
    "/delete",
    response_model=DeleteBackupsResponse,
    summary="Delete backups",
)
async def delete_backups_route(req: DeleteBackupsRequest):
    return await delete_backups(req.ids)


async def _handle_pending_import(pending_token: str) -> BackupMeta:
    """Resume an import that was paused due to a conflict (409).

    The presence of *pending_token* signals that the user has confirmed the
    overwrite in the UI, so the import is retried with ``overwrite=True``.

    Validates the token against BACKUP_DIR to prevent path traversal, then
    removes the temp file when done (whether the import succeeds or fails).
    """
    tmp_path = (BACKUP_DIR / pending_token).resolve()
    # Guard against path traversal: resolved path must stay inside BACKUP_DIR
    if not tmp_path.is_relative_to(BACKUP_DIR.resolve()):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    if not tmp_path.is_file() or tmp_path.suffix != ".upload_tmp":
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired pending_token",
        )
    try:
        return await import_backup(tmp_path, overwrite=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


async def _handle_fresh_upload(
    file: UploadFile,
) -> BackupMeta | JSONResponse:
    """Save the uploaded zip to a temp file and attempt an import.

    Returns the imported BackupMeta on success.  On a backup-ID conflict
    returns a 409 JSONResponse containing the existing meta and a
    pending_token; the temp file is kept so the client can retry without
    re-uploading.
    """
    if file.content_type and file.content_type not in (
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, got"
                f" content-type: {file.content_type}"
            ),
        )

    tmp_fd, tmp_name = tempfile.mkstemp(dir=BACKUP_DIR, suffix=".upload_tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as fp:
            while chunk := await file.read(1024 * 1024):
                fp.write(chunk)

        result = await import_backup(tmp_path)
        # The no-conflict path renames tmp_path → dest (unlink is a no-op).
        # Other paths only read tmp_path, so we always clean up here.
        tmp_path.unlink(missing_ok=True)
        return result
    except BackupConflictError as exc:
        # Keep the temp file: client can retry using the pending_token.
        meta = exc.existing_meta
        return JSONResponse(
            status_code=409,
            content={
                "detail": "backup_conflict",
                "existing": meta.model_dump(mode="json"),
                "pending_token": tmp_path.name,
            },
        )
    except ValueError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/import", response_model=BackupMeta, summary="Import backup zip")
async def import_backup_route(
    file: UploadFile = File(default=None, description="Backup zip archive"),
    pending_token: str | None = Form(default=None),
):
    """Import a backup zip uploaded by the client.

    On the first call the client sends ``file`` only.  If the backup ID
    already exists, the server keeps the uploaded temp file and returns
    **409** with ``pending_token`` and the existing backup's metadata.
    The client then re-sends with ``pending_token`` only (no file upload
    needed) to confirm the overwrite and finish the import.
    """
    _cleanup_stale_uploads()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if pending_token:
        return await _handle_pending_import(pending_token)

    if file is None:
        raise HTTPException(status_code=400, detail="file is required")

    return await _handle_fresh_upload(file)


@router.get(
    "/{backup_id}",
    response_model=BackupDetail,
    summary="Backup detail",
)
async def get_backup_route(backup_id: str):
    detail = await get_backup(backup_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return detail


@router.post("/{backup_id}/restore", summary="Restore backup")
async def restore_backup(
    backup_id: str,
    req: RestoreBackupRequest,
    request: Request,
):
    manager = getattr(request.app.state, "multi_agent_manager", None)
    try:
        await execute_restore(
            backup_id,
            req,
            stop_agent_fn=manager.stop_agent if manager else None,
            preload_agent_fn=manager.preload_agent if manager else None,
            list_running_agent_ids_fn=(
                manager.list_loaded_agents if manager else None
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Backup not found",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True}


@router.get("/{backup_id}/export", summary="Export backup as zip")
async def export_backup_route(backup_id: str):
    try:
        zip_path, _ = await export_backup(backup_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Backup not found",
        ) from exc

    filename = f"{backup_id}.zip"

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=filename,
    )
