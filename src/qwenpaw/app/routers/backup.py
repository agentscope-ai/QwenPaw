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

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
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
    BackupTrustMode,
    BackupValidationError,
    CreateBackupRequest,
    DeleteBackupsRequest,
    DeleteBackupsResponse,
    RestoreBackupRequest,
)
from ...constant import BACKUP_DIR
from ...identity.runtime import is_multi_user_enabled
from ...access.actor import ActorContext
from ...access.dependencies import require_platform_settings_manage
from ...agents.tools import shutdown_browsers_for_workspace_dirs
from ._backup_helpers import (
    backup_contains_global_config,
    parse_pending_token,
    restored_local_keys,
    strip_signature,
    upload_suffix_for_trust_mode,
    validation_detail,
)
from ...backup._ops.restore import preflight_restore
from ...platform_ops.backup_service import (
    RestoreConfirmationError,
    RestoreImpact,
    append_platform_snapshot,
    consume_restore_confirmation,
    create_pre_restore_backup,
    create_restore_preview,
    restore_platform_database,
    create_platform_stream,
    validate_platform_restore,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/backups",
    tags=["backups"],
    dependencies=[Depends(require_platform_settings_manage)],
)

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


@router.post("/stream", summary="Create backup with SSE progress stream")
async def create_backup_stream(req: CreateBackupRequest):
    """Create a backup and stream progress via SSE.

    When the client disconnects the background thread stops at the next agent
    boundary without writing the final file. Each event is formatted as
    `data: <json>\\n\\n`; see create_stream for event shapes.
    """

    async def generate():
        completed_backup_id: str | None = None
        try:
            async for event in create_platform_stream(req, file_stream=create_stream):
                if event.get("type") == "done":
                    completed_backup_id = str(event["meta"]["id"])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            if completed_backup_id is not None:
                await delete_backups([completed_backup_id])
            logger.error(
                "Backup creation failed (error_type=%s)",
                type(exc).__name__,
            )
            payload = {"type": "error", "message": "backup_creation_failed"}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        # Disable proxy/nginx buffering so events reach the client immediately
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
        logger.error("Backup import failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="backup_import_failed") from exc
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
            detail=("Expected a zip file, got" f" content-type: {file.content_type}"),
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
        logger.error("Backup import failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="backup_import_failed") from exc


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
    actor: ActorContext = Depends(require_platform_settings_manage),
):
    if is_multi_user_enabled():
        actor_id = str(actor.user_id or "legacy-admin")
        try:
            consume_restore_confirmation(
                req.confirmation_token,
                backup_id,
                req,
                actor_id=actor_id,
            )
        except RestoreConfirmationError as exc:
            raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    manager = getattr(request.app.state, "multi_agent_manager", None)
    pre_restore_backup_ids: list[str] = []

    async def create_protection_backup() -> str:
        backup = await create_pre_restore_backup()
        pre_restore_backup_ids.append(backup)
        return backup

    try:
        validate_platform_restore(backup_id, req)
        meta = await execute_restore(
            backup_id,
            req,
            stop_agent_fn=manager.stop_agent if manager else None,
            # Contractual order: stop agent, browsers, then replace files.
            stop_browsers_fn=shutdown_browsers_for_workspace_dirs,
            preload_agent_fn=manager.preload_agent if manager else None,
            list_running_agent_ids_fn=(manager.list_loaded_agents if manager else None),
            create_pre_restore_backup_fn=(
                create_protection_backup if is_multi_user_enabled() else None
            ),
            restore_database_fn=(
                restore_platform_database if is_multi_user_enabled() else None
            ),
        )
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
        logger.error("Backup restore failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="backup_restore_failed") from exc

    preserved = restored_local_keys(
        req,
        meta,
        archive_has_global_config=backup_contains_global_config(backup_id),
    )
    return {
        "ok": True,
        "preserved_local_keys": preserved,
        "pre_restore_backup_id": (
            pre_restore_backup_ids[0] if pre_restore_backup_ids else None
        ),
    }


@router.post(
    "/{backup_id}/restore/preview",
    response_model=RestoreImpact,
    summary="Preview platform restore impact",
)
async def preview_backup_restore(
    backup_id: str,
    req: RestoreBackupRequest,
    actor: ActorContext = Depends(require_platform_settings_manage),
):
    detail = await get_backup(backup_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    try:
        await asyncio.to_thread(preflight_restore, backup_id, req)
    except BackupValidationError as exc:
        raise HTTPException(status_code=400, detail=validation_detail(exc)) from exc
    return create_restore_preview(
        backup_id,
        req,
        detail,
        actor_id=str(actor.user_id or "legacy-admin"),
    )


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
