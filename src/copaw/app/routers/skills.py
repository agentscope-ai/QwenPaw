# -*- coding: utf-8 -*-
"""Workspace and skill-pool APIs."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...agents.skills_hub import (
    SkillImportCancelled,
    search_hub_skills,
    import_pool_skill_from_hub,
    install_skill_from_hub,
)
from ...agents.skills_manager import (
    SkillPoolService,
    SkillInfo,
    SkillService,
    _default_pool_manifest,
    _default_workspace_manifest,
    _mutate_json,
    fetch_latest_builtin_skills,
    get_pool_skill_manifest_path,
    get_workspace_skill_manifest_path,
    list_workspaces,
    read_skill_pool_manifest,
    read_skill_manifest,
    reconcile_workspace_manifest,
)
from ...security.skill_scanner import SkillScanError
from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])


def _scan_error_payload(exc: SkillScanError) -> dict[str, Any]:
    """Normalize scanner exceptions into a stable API payload.

    Example response body:
        {
            "type": "security_scan_failed",
            "skill_name": "blocked_skill",
            "max_severity": "high",
            "findings": [...]
        }
    """
    result = exc.result
    return {
        "type": "security_scan_failed",
        "detail": str(exc),
        "skill_name": result.skill_name,
        "max_severity": result.max_severity.value,
        "findings": [
            {
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "rule_id": f.rule_id,
            }
            for f in result.findings
        ],
    }


def _scan_error_response(exc: SkillScanError) -> JSONResponse:
    """Build the historical 422 response shape used by skill endpoints.

    We intentionally return a real HTTP 422 response object here so callers
    and tests observe the same behavior as before the skill-pool refactor.
    """
    return JSONResponse(
        status_code=422,
        content=_scan_error_payload(exc),
    )


class SkillSpec(SkillInfo):
    enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["all"])
    sync_to_pool: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class PoolSkillSpec(SkillInfo):
    protected: bool = False
    version_text: str = ""
    commit_text: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class WorkspaceSkillSummary(BaseModel):
    agent_id: str
    workspace_dir: str
    skills: list[SkillSpec] = Field(default_factory=list)


class HubSkillSpec(BaseModel):
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


class FetchLatestBuiltinRequest(BaseModel):
    approve_conflicts: bool = False
    preview_only: bool = False


class CreateSkillRequest(BaseModel):
    name: str
    content: str
    overwrite: bool = True
    references: dict[str, Any] | None = None
    scripts: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class UploadToPoolRequest(BaseModel):
    workspace_id: str
    skill_name: str
    new_name: str | None = None
    overwrite: bool = False


class PoolDownloadTarget(BaseModel):
    workspace_id: str
    target_name: str | None = None


class DownloadFromPoolRequest(BaseModel):
    skill_name: str
    targets: list[PoolDownloadTarget] = Field(default_factory=list)
    all_workspaces: bool = False
    overwrite: bool = False


class SkillConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SavePoolSkillRequest(CreateSkillRequest):
    source_name: str | None = None


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    enable: bool = Field(default=False, description="Enable after import")
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing workspace skill",
    )


class HubInstallTaskStatus(str, Enum):
    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HubInstallTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bundle_url: str
    version: str = ""
    enable: bool = False
    overwrite: bool = False
    status: HubInstallTaskStatus = HubInstallTaskStatus.PENDING
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


_hub_install_tasks: dict[str, HubInstallTask] = {}
_hub_install_runtime_tasks: dict[str, asyncio.Task] = {}
_hub_install_cancel_events: dict[str, threading.Event] = {}
_hub_install_lock = asyncio.Lock()

_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


def _workspace_dir_for_agent(agent_id: str) -> Path:
    for workspace in list_workspaces():
        if workspace["agent_id"] == agent_id:
            return Path(workspace["workspace_dir"])
    raise HTTPException(
        status_code=404,
        detail=f"Workspace '{agent_id}' not found",
    )


async def _request_workspace_dir(request: Request) -> Path:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return Path(workspace.workspace_dir)


async def _hub_task_set_status(
    task_id: str,
    status: HubInstallTaskStatus,
    *,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.updated_at = time.time()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result


async def _hub_task_get(task_id: str) -> HubInstallTask | None:
    async with _hub_install_lock:
        return _hub_install_tasks.get(task_id)


async def _hub_task_register_runtime(task_id: str, task: asyncio.Task) -> None:
    async with _hub_install_lock:
        _hub_install_runtime_tasks[task_id] = task


async def _hub_task_pop_runtime(task_id: str) -> asyncio.Task | None:
    async with _hub_install_lock:
        return _hub_install_runtime_tasks.pop(task_id, None)


async def _read_validated_zip_upload(file: UploadFile) -> bytes:
    if file.content_type and file.content_type not in _ALLOWED_ZIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, "
                f"got content-type: {file.content_type}"
            ),
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(data) // (1024 * 1024)} MB). "
                f"Maximum is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )
    return data


def _cleanup_imported_skill(workspace_dir: Path, skill_name: str) -> None:
    if not skill_name:
        return
    try:
        skill_service = SkillService(workspace_dir)
        skill_service.disable_skill(skill_name)
        skill_service.delete_skill(skill_name)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Cleanup after cancelled import failed for '%s': %s",
            skill_name,
            exc,
        )


async def _run_hub_install_task(
    *,
    task_id: str,
    workspace_dir: Path,
    body: HubInstallRequest,
    cancel_event: threading.Event,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    imported_skill_name: str | None = None
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: install_skill_from_hub(
                workspace_dir=workspace_dir,
                bundle_url=body.bundle_url,
                version=body.version,
                enable=body.enable,
                overwrite=body.overwrite,
                cancel_checker=cancel_event.is_set,
            ),
        )
        imported_skill_name = result.name
        if cancel_event.is_set():
            _cleanup_imported_skill(workspace_dir, result.name)
            await _hub_task_set_status(
                task_id,
                HubInstallTaskStatus.CANCELLED,
                result={
                    "installed": False,
                    "name": result.name,
                    "enabled": False,
                    "source_url": result.source_url,
                },
            )
            return
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.COMPLETED,
            result={
                "installed": True,
                "name": result.name,
                "enabled": result.enabled,
                "source_url": result.source_url,
            },
        )
    except SkillImportCancelled:
        if imported_skill_name:
            _cleanup_imported_skill(workspace_dir, imported_skill_name)
        await _hub_task_set_status(task_id, HubInstallTaskStatus.CANCELLED)
    except SkillScanError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=_scan_error_payload(exc),
        )
    except ValueError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except RuntimeError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except Exception as exc:  # pragma: no cover
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {exc}",
        )
    finally:
        await _hub_task_pop_runtime(task_id)


def _build_workspace_skill_specs(workspace_dir: Path) -> list[SkillSpec]:
    manifest = read_skill_manifest(workspace_dir)
    service = SkillService(workspace_dir)
    entries = manifest.get("skills", {})
    specs: list[SkillSpec] = []
    for skill in service.list_all_skills():
        entry = entries.get(skill.name, {})
        specs.append(
            SkillSpec(
                **skill.model_dump(),
                enabled=entry.get("enabled", False),
                channels=entry.get("channels") or ["all"],
                sync_to_pool=entry.get("sync_to_pool") or {},
                config=entry.get("config") or {},
            ),
        )
    return specs


def _build_pool_skill_specs() -> list[PoolSkillSpec]:
    manifest = read_skill_pool_manifest()
    service = SkillPoolService()
    entries = manifest.get("skills", {})
    specs: list[PoolSkillSpec] = []
    for skill in service.list_all_skills():
        entry = entries.get(skill.name, {})
        specs.append(
            PoolSkillSpec(
                **skill.model_dump(),
                protected=bool(entry.get("protected", False)),
                version_text=str(entry.get("version_text", "") or ""),
                commit_text=str(entry.get("commit_text", "") or ""),
                config=entry.get("config") or {},
            ),
        )
    return specs


@router.get("")
async def list_skills(request: Request) -> list[SkillSpec]:
    workspace_dir = await _request_workspace_dir(request)
    return _build_workspace_skill_specs(workspace_dir)


@router.get("/hub/search")
async def search_hub(
    q: str = "",
    limit: int = 20,
) -> list[HubSkillSpec]:
    results = search_hub_skills(q, limit=limit)
    return [
        HubSkillSpec(
            slug=item.slug,
            name=item.name,
            description=item.description,
            version=item.version,
            source_url=item.source_url,
        )
        for item in results
    ]


@router.get("/workspaces")
async def list_workspace_skill_sources() -> list[WorkspaceSkillSummary]:
    summaries: list[WorkspaceSkillSummary] = []
    for workspace in list_workspaces():
        workspace_dir = Path(workspace["workspace_dir"])
        summaries.append(
            WorkspaceSkillSummary(
                agent_id=workspace["agent_id"],
                workspace_dir=str(workspace_dir),
                skills=_build_workspace_skill_specs(workspace_dir),
            ),
        )
    return summaries


@router.post("/hub/install/start", response_model=HubInstallTask)
async def start_install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
) -> HubInstallTask:
    workspace_dir = await _request_workspace_dir(request)
    task = HubInstallTask(
        bundle_url=request_body.bundle_url,
        version=request_body.version,
        enable=request_body.enable,
        overwrite=request_body.overwrite,
    )
    cancel_event = threading.Event()
    async with _hub_install_lock:
        _hub_install_tasks[task.task_id] = task
        _hub_install_cancel_events[task.task_id] = cancel_event

    runtime_task = asyncio.create_task(
        _run_hub_install_task(
            task_id=task.task_id,
            workspace_dir=workspace_dir,
            body=request_body,
            cancel_event=cancel_event,
        ),
        name=f"skill-hub-install-{task.task_id}",
    )
    await _hub_task_register_runtime(task.task_id, runtime_task)
    return task


@router.get("/hub/install/status/{task_id}", response_model=HubInstallTask)
async def get_hub_install_status(task_id: str) -> HubInstallTask:
    task = await _hub_task_get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="install task not found")
    return task


@router.post("/hub/install/cancel/{task_id}")
async def cancel_hub_install(task_id: str) -> dict[str, Any]:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="install task not found",
            )
        if task.status in (
            HubInstallTaskStatus.COMPLETED,
            HubInstallTaskStatus.FAILED,
            HubInstallTaskStatus.CANCELLED,
        ):
            return {"task_id": task_id, "status": task.status.value}
        cancel_event = _hub_install_cancel_events.get(task_id)
        if cancel_event is not None:
            cancel_event.set()
        task.status = HubInstallTaskStatus.CANCELLED
        task.updated_at = time.time()
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/pool")
async def list_pool_skills() -> list[PoolSkillSpec]:
    return _build_pool_skill_specs()


@router.post("")
async def create_skill(
    request: Request,
    body: CreateSkillRequest,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    try:
        created = SkillService(workspace_dir).create_skill(
            name=body.name,
            content=body.content,
            overwrite=body.overwrite,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not created:
        raise HTTPException(status_code=409, detail="Skill already exists")
    reconcile_workspace_manifest(workspace_dir)
    return {"created": True, "name": created}


@router.post("/upload")
async def upload_skill_zip(
    request: Request,
    file: UploadFile = File(...),
    enable: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    data = await _read_validated_zip_upload(file)
    try:
        result = SkillService(workspace_dir).import_from_zip(
            data=data,
            overwrite=overwrite,
            enable=enable,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/pool/create")
async def create_pool_skill(body: CreateSkillRequest) -> dict[str, Any]:
    try:
        created = SkillPoolService().create_skill(
            name=body.name,
            content=body.content,
            overwrite=body.overwrite,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not created:
        raise HTTPException(
            status_code=409,
            detail="Skill pool entry already exists",
        )
    return {"created": True, "name": created}


@router.put("/pool/save")
async def save_pool_skill(body: SavePoolSkillRequest) -> dict[str, Any]:
    """Edit, rename, or fork a pool skill depending on current ownership.

    Example:
    - editing a normal shared skill in place -> ``mode="edit"``
    - renaming a non-builtin shared skill -> ``mode="rename"``
    - editing a protected builtin -> ``mode="fork"``
    """
    service = SkillPoolService()
    try:
        result = service.save_pool_skill(
            skill_name=body.source_name or body.name,
            target_name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not result.get("success"):
        reason = result.get("reason")
        status = 404 if reason == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


@router.post("/pool/upload-zip")
async def upload_skill_pool_zip(
    file: UploadFile = File(...),
    overwrite: bool = False,
) -> dict[str, Any]:
    data = await _read_validated_zip_upload(file)
    try:
        return SkillPoolService().import_from_zip(
            data=data,
            overwrite=overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pool/import")
async def import_skill_pool_from_hub(
    body: HubInstallRequest,
) -> dict[str, Any]:
    try:
        result = import_pool_skill_from_hub(
            bundle_url=body.bundle_url,
            version=body.version,
            overwrite=body.overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "installed": True,
        "name": result.name,
        "enabled": False,
        "source_url": result.source_url,
    }


@router.post("/pool/upload")
async def upload_workspace_skill_to_pool(
    body: UploadToPoolRequest,
) -> dict[str, Any]:
    workspace_dir = _workspace_dir_for_agent(body.workspace_id)
    result = SkillPoolService().upload_from_workspace(
        workspace_dir=workspace_dir,
        skill_name=body.skill_name,
        target_name=body.new_name,
        overwrite=body.overwrite,
    )
    if not result.get("success"):
        status = 404 if result.get("reason") == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


@router.post("/pool/download")
async def download_pool_skill_to_workspaces(
    body: DownloadFromPoolRequest,
) -> dict[str, Any]:
    """Download one pool skill into one or more workspaces.

    Behavior:
    - first run a preflight for every target
    - if any target conflicts, abort the whole operation with 409
    - only copy files after all targets are safe

    Example:
        downloading ``shared_demo`` to workspaces ``a1`` and ``b1`` returns
        409 if ``b1`` already has a conflicting local skill, even if ``a1``
        would have succeeded.
    """
    targets = list(body.targets)
    if body.all_workspaces:
        targets = [
            PoolDownloadTarget(workspace_id=workspace["agent_id"])
            for workspace in list_workspaces()
        ]

    if not targets:
        raise HTTPException(
            status_code=400,
            detail="No workspace targets provided",
        )

    hub_service = SkillPoolService()
    conflicts: list[dict[str, Any]] = []
    planned: list[tuple[PoolDownloadTarget, Path, dict[str, Any]]] = []

    for target in targets:
        workspace_dir = _workspace_dir_for_agent(target.workspace_id)
        result = hub_service.preflight_download_to_workspace(
            skill_name=body.skill_name,
            workspace_dir=workspace_dir,
            target_name=target.target_name,
            overwrite=body.overwrite,
        )
        if not result.get("success"):
            conflicts.append(result)
            continue
        planned.append((target, workspace_dir, result))

    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={"downloaded": [], "conflicts": conflicts},
        )

    downloaded: list[dict[str, str]] = []
    for target, workspace_dir, _ in planned:
        result = hub_service.download_to_workspace(
            skill_name=body.skill_name,
            workspace_dir=workspace_dir,
            target_name=target.target_name,
            overwrite=body.overwrite,
        )
        if not result.get("success"):
            conflicts.append(result)
            continue
        downloaded.append(
            {
                "workspace_id": target.workspace_id,
                "name": str(result.get("name", "")),
            },
        )

    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={"downloaded": downloaded, "conflicts": conflicts},
        )

    return {"downloaded": downloaded}


@router.post("/pool/fetch-latest")
async def fetch_latest_builtins(
    body: FetchLatestBuiltinRequest,
) -> dict[str, Any]:
    return fetch_latest_builtin_skills(
        approve_conflicts=body.approve_conflicts,
        preview_only=body.preview_only,
    )


@router.delete("/pool/{skill_name}")
async def delete_pool_skill(skill_name: str) -> dict[str, Any]:
    deleted = SkillPoolService().delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Skill pool entry cannot be deleted",
        )
    return {"deleted": True}


@router.get("/pool/{skill_name}/config")
async def get_pool_skill_config(skill_name: str) -> dict[str, Any]:
    manifest = read_skill_pool_manifest()
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"config": entry.get("config", {})}


@router.put("/pool/{skill_name}/config")
async def update_pool_skill_config(
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = _mutate_json(manifest_path, _default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"updated": True}


@router.delete("/pool/{skill_name}/config")
async def delete_pool_skill_config(skill_name: str) -> dict[str, Any]:
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = _mutate_json(manifest_path, _default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"cleared": True}


@router.post("/batch-disable")
async def batch_disable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results = {skill: service.disable_skill(skill) for skill in skills}
    return {"results": results}


@router.post("/batch-enable")
async def batch_enable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Enable each requested skill independently and collect per-skill results.

    Example:
        enabling ``["ok_skill", "blocked_skill"]`` returns success for the
        first item and ``reason="security_scan_failed"`` for the second,
        rather than aborting the entire batch.
    """
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill in skills:
        try:
            results[skill] = service.enable_skill(skill)
        except SkillScanError as exc:
            results[skill] = {
                "success": False,
                "reason": "security_scan_failed",
                "detail": _scan_error_payload(exc),
            }
    return {"results": results}


@router.post("/{skill_name}/disable")
async def disable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    result = SkillService(workspace_dir).disable_skill(skill_name)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"disabled": True, **result}


@router.post("/{skill_name}/enable")
async def enable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    """Enable one workspace skill after a fresh scan."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    try:
        result = SkillService(workspace_dir).enable_skill(skill_name)
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not result.get("success"):
        raise HTTPException(
            status_code=404,
            detail=result.get("reason", "Skill not found"),
        )
    schedule_agent_reload(request, workspace.agent_id)
    return {"enabled": True, **result}


@router.delete("/{skill_name}")
async def delete_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    deleted = SkillService(workspace_dir).delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Only disabled workspace skills can be deleted",
        )
    return {"deleted": True}


@router.get("/{skill_name}/files/{source}/{file_path:path}")
async def load_skill_file(
    request: Request,
    skill_name: str,
    source: str,
    file_path: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    content = SkillService(workspace_dir).load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
        source=source,
    )
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": content}


@router.put("/{skill_name}/channels")
async def update_skill_channels_endpoint(
    request: Request,
    skill_name: str,
    channels: list[str],
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    updated = SkillService(workspace_dir).set_skill_channels(
        skill_name,
        channels,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True, "channels": channels}


@router.get("/{skill_name}/config")
async def get_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"config": entry.get("config", {})}


@router.put("/{skill_name}/config")
async def update_skill_config_endpoint(
    request: Request,
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True}


@router.delete("/{skill_name}/config")
async def delete_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = _mutate_json(
        manifest_path,
        _default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"cleared": True}
