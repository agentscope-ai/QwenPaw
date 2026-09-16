# -*- coding: utf-8 -*-
"""Backup API – create, list, restore, delete, export, import."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ...backup import (
    BackupManager,
    BackupOperationConflict,
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
    BackupJobPhase,
    BackupJobSnapshot,
    BackupJobStatus,
    BackupMeta,
    BackupTrustMode,
    BackupValidationError,
    CreateBackupRequest,
    DeleteBackupsRequest,
    DeleteBackupsResponse,
    RestoreBackupRequest,
)
from ...constant import BACKUP_DIR
from ...agents.tools import shutdown_browsers_for_workspace_dirs
from ._backup_helpers import (
    backup_contains_global_config,
    parse_pending_token,
    restored_local_keys,
    strip_signature,
    upload_suffix_for_trust_mode,
    validation_detail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backups", tags=["backups"])

_UPLOAD_TMP_MAX_AGE = 3600  # 1 hour
_SSE_HEARTBEAT_SECONDS = 15.0


def _get_backup_manager(request: Request) -> BackupManager:
    manager = getattr(request.app.state, "backup_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Backup manager is not available",
        )
    return manager


def _legacy_event(snapshot: BackupJobSnapshot) -> dict:
    """Map a job snapshot to the legacy stream event shape."""
    if snapshot.status == BackupJobStatus.COMPLETED:
        return {
            "type": "done",
            "meta": snapshot.result.model_dump(mode="json"),
            "percent": 100,
        }
    if snapshot.status in {
        BackupJobStatus.FAILED,
        BackupJobStatus.CANCELLED,
    }:
        return {
            "type": "error",
            "message": snapshot.error or "Backup cancelled",
        }
    if snapshot.phase == BackupJobPhase.FINALIZING:
        return {"type": "saving", "percent": snapshot.percent}
    if snapshot.current_agent:
        return {
            "type": "agent",
            "agent_id": snapshot.current_agent,
            "index": snapshot.agent_index,
            "total": snapshot.total_agents,
            "percent": snapshot.percent,
        }
    return {
        "type": "start",
        "total_agents": snapshot.total_agents,
        "percent": 0,
    }


async def _job_event_stream(
    manager: BackupManager,
    job_id: str,
    *,
    legacy: bool = False,
):
    queue = manager.subscribe(job_id)
    if queue is None:
        return
    try:
        while True:
            try:
                snapshot = await asyncio.wait_for(
                    queue.get(),
                    timeout=_SSE_HEARTBEAT_SECONDS,
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            payload = (
                _legacy_event(snapshot)
                if legacy
                else snapshot.model_dump(mode="json")
            )
            yield f"data: {json.dumps(payload)}\n\n"
            if snapshot.status in {
                BackupJobStatus.COMPLETED,
                BackupJobStatus.FAILED,
                BackupJobStatus.CANCELLED,
            }:
                break
    finally:
        manager.unsubscribe(job_id, queue)


def _stream_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    for pattern in (
        "*.upload_tmp",
        "*.upload_tmp.trust",
        "*.upload_tmp.trust_legacy",
        "*.upload_tmp.trust_foreign",
        "*.tmp",
    ):
        for f in BACKUP_DIR.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except OSError:
                pass


@router.post(
    "/jobs",
    response_model=BackupJobSnapshot,
    status_code=202,
    summary="Start a backup creation job",
)
async def start_backup_job(req: CreateBackupRequest, request: Request):
    manager = _get_backup_manager(request)
    try:
        return manager.start_job(req)
    except BackupOperationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/jobs/active",
    response_model=BackupJobSnapshot | None,
    summary="Get the active backup creation job",
)
async def get_active_backup_job(request: Request):
    return _get_backup_manager(request).get_active_job()


@router.get(
    "/jobs/{job_id}",
    response_model=BackupJobSnapshot,
    summary="Get a backup creation job",
)
async def get_backup_job(job_id: str, request: Request):
    snapshot = _get_backup_manager(request).get_job(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Backup job not found")
    return snapshot


@router.get(
    "/jobs/{job_id}/events",
    summary="Observe a backup creation job via SSE",
)
async def backup_job_events(job_id: str, request: Request):
    manager = _get_backup_manager(request)
    if manager.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Backup job not found")
    return _stream_response(_job_event_stream(manager, job_id))


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=BackupJobSnapshot,
    summary="Cancel a backup creation job",
)
async def cancel_backup_job(job_id: str, request: Request):
    snapshot = _get_backup_manager(request).cancel_job(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Backup job not found")
    return snapshot


@router.post("/stream", summary="Create backup with SSE progress stream")
async def create_backup_stream(req: CreateBackupRequest, request: Request):
    """Compatibility adapter over the application-owned backup job."""
    manager = _get_backup_manager(request)
    try:
        snapshot = manager.start_job(req)
    except BackupOperationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _stream_response(
        _job_event_stream(manager, snapshot.job_id, legacy=True),
    )


@router.get("", response_model=list[BackupMeta], summary="List backups")
async def list_backups_route():
    return [strip_signature(meta) for meta in await list_backups()]


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
    The token suffix also carries the original explicit trust mode, avoiding a
    second trust prompt on conflict retry while keeping the server-side trust
    decision tied to the temp file.

    Validates the token against BACKUP_DIR to prevent path traversal, then
    removes the temp file when done (whether the import succeeds or fails).
    """
    tmp_path, trust_mode = parse_pending_token(pending_token)
    try:
        return await import_backup(
            tmp_path,
            overwrite=True,
            trust_mode=trust_mode,
        )
    except BackupValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=validation_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


async def _handle_fresh_upload(
    file: UploadFile,
    *,
    trust_mode: BackupTrustMode | None = None,
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

    suffix = upload_suffix_for_trust_mode(trust_mode)
    # Keep trusted and untrusted pending uploads distinguishable after a 409
    # conflict. The retry endpoint only accepts filenames inside BACKUP_DIR.
    tmp_fd, tmp_name = tempfile.mkstemp(dir=BACKUP_DIR, suffix=suffix)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as fp:
            while chunk := await file.read(1024 * 1024):
                fp.write(chunk)

        result = await import_backup(tmp_path, trust_mode=trust_mode)
        # The no-conflict path renames tmp_path to dest (unlink is a no-op).
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
                "existing": strip_signature(meta).model_dump(mode="json"),
                "pending_token": tmp_path.name,
            },
        )
    except BackupValidationError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=validation_detail(exc),
        ) from exc
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
    trust_mode: BackupTrustMode | None = Form(default=None),
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

    return await _handle_fresh_upload(file, trust_mode=trust_mode)


@router.get(
    "/{backup_id}",
    response_model=BackupDetail,
    summary="Backup detail",
)
async def get_backup_route(backup_id: str):
    detail = await get_backup(backup_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    payload = strip_signature(detail).model_dump()
    payload["workspace_stats"] = detail.workspace_stats
    return BackupDetail.model_validate(payload)


@router.post("/{backup_id}/restore", summary="Restore backup")
async def restore_backup(
    backup_id: str,
    req: RestoreBackupRequest,
    request: Request,
):
    backup_manager = _get_backup_manager(request)
    agent_manager = getattr(request.app.state, "multi_agent_manager", None)
    try:
        with backup_manager.reserve_restore():
            meta = await execute_restore(
                backup_id,
                req,
                stop_agent_fn=(
                    agent_manager.stop_agent if agent_manager else None
                ),
                # Contractual order: stop agent, browsers, then replace files.
                stop_browsers_fn=shutdown_browsers_for_workspace_dirs,
                preload_agent_fn=(
                    agent_manager.preload_agent if agent_manager else None
                ),
                list_running_agent_ids_fn=(
                    agent_manager.list_loaded_agents if agent_manager else None
                ),
            )
    except BackupOperationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Backup not found",
        ) from exc
    except BackupValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=validation_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    preserved = restored_local_keys(
        req,
        meta,
        archive_has_global_config=backup_contains_global_config(backup_id),
    )
    return {"ok": True, "preserved_local_keys": preserved}


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
