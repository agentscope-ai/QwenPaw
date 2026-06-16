# -*- coding: utf-8 -*-
"""File baseline protection API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pathlib import Path

from ...security.extension_host import get_file_baseline_service, stream_file_baseline_events
from ...security.file_baseline_bridge import browse_workspace_protectable_files
from ..agent_context import get_agent_for_request
from .schemas_integrity_delivery import (
    FileBaselineProtectionActionRequest,
    FileBaselineProtectionActionResponse,
    FileBaselineProtectionAlertsResponse,
    FileBaselineProtectionSettingsResponse,
    FileBaselineProtectionSettingsUpdateRequest,
    FileBaselineWorkspaceBrowseResponse,
)

router = APIRouter(tags=["config"])


@router.get(
    "/security/file-baseline/settings",
    response_model=FileBaselineProtectionSettingsResponse,
    summary="Get file baseline protection settings",
)
async def get_file_baseline_protection_settings() -> FileBaselineProtectionSettingsResponse:
    return FileBaselineProtectionSettingsResponse(
        **get_file_baseline_service().get_settings_payload(),
    )


@router.put(
    "/security/file-baseline/settings",
    response_model=FileBaselineProtectionSettingsResponse,
    summary="Update file baseline protection settings",
)
async def update_file_baseline_protection_settings(
    body: FileBaselineProtectionSettingsUpdateRequest,
) -> FileBaselineProtectionSettingsResponse:
    service = get_file_baseline_service()
    try:
        payload = await service.update_settings(
            enabled=body.enabled,
            protected_targets=body.protected_targets,
            confirmation_phrase=body.confirmation_phrase,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileBaselineProtectionSettingsResponse(**payload)


@router.get(
    "/security/file-baseline/browse",
    response_model=FileBaselineWorkspaceBrowseResponse,
    summary="Browse agent workspace files for protected path picker",
)
async def browse_file_baseline_workspace_files(
    request: Request,
    path: str = "skills",
) -> FileBaselineWorkspaceBrowseResponse:
    workspace = await get_agent_for_request(request)
    try:
        payload = browse_workspace_protectable_files(
            workspace_dir=Path(workspace.workspace_dir),
            agent_id=workspace.agent_id,
            relative_path=path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileBaselineWorkspaceBrowseResponse(**payload)


@router.get(
    "/security/file-baseline/alerts",
    response_model=FileBaselineProtectionAlertsResponse,
    summary="List open file baseline drift alerts",
)
async def get_file_baseline_protection_alerts() -> FileBaselineProtectionAlertsResponse:
    payload = await get_file_baseline_service().list_alerts()
    return FileBaselineProtectionAlertsResponse(**payload)


@router.post(
    "/security/file-baseline/restore",
    response_model=FileBaselineProtectionActionResponse,
    summary="Restore file from approved baseline (P2)",
)
async def restore_file_baseline_protection_alert(
    body: FileBaselineProtectionActionRequest,
) -> FileBaselineProtectionActionResponse:
    service = get_file_baseline_service()
    if not service.is_enabled():
        raise HTTPException(status_code=403, detail="file baseline protection disabled")
    result = await service.restore(
        alert_id=body.alert_id,
        confirmation_phrase=body.confirmation_phrase,
    )
    return FileBaselineProtectionActionResponse(**result)


@router.post(
    "/security/file-baseline/accept",
    response_model=FileBaselineProtectionActionResponse,
    summary="Accept current file as new baseline (P2)",
)
async def accept_file_baseline_protection_alert(
    body: FileBaselineProtectionActionRequest,
) -> FileBaselineProtectionActionResponse:
    service = get_file_baseline_service()
    if not service.is_enabled():
        raise HTTPException(status_code=403, detail="file baseline protection disabled")
    result = await service.accept(
        alert_id=body.alert_id,
        confirmation_phrase=body.confirmation_phrase,
    )
    return FileBaselineProtectionActionResponse(**result)


@router.get(
    "/security/file-baseline/watch",
    summary="SSE stream for file baseline drift and baseline updates",
)
async def watch_file_baseline_protection(request: Request) -> StreamingResponse:
    return StreamingResponse(
        stream_file_baseline_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
