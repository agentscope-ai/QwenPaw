# -*- coding: utf-8 -*-
import asyncio
import logging
import shutil
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...agents.skills_manager import (
    SkillService,
    SkillInfo,
    get_builtin_skills_dir,
    get_inactive_skills_dir,
)
from ...agents.skills_hub import (
    SkillImportCancelled,
    install_skill_from_hub_to_builtin,
)
from ...security.skill_scanner import SkillScanError


logger = logging.getLogger(__name__)


def _scan_error_response(exc: SkillScanError) -> JSONResponse:
    """Build a 422 response with structured scan findings."""
    result = exc.result
    return JSONResponse(
        status_code=422,
        content={
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
        },
    )


class DefaultSkillSpec(SkillInfo):
    enabled: bool = False


class CreateDefaultSkillRequest(BaseModel):
    name: str = Field(..., description="Skill name")
    content: str = Field(..., description="Skill content (SKILL.md)")
    references: dict[str, Any] | None = Field(
        None,
        description="Optional tree structure for references/.",
    )
    scripts: dict[str, Any] | None = Field(
        None,
        description="Optional tree structure for scripts/.",
    )


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing builtin skill",
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


async def _run_hub_install_task(
    *,
    task_id: str,
    body: HubInstallRequest,
    cancel_event: threading.Event,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    result_payload: dict[str, Any] | None = None
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: install_skill_from_hub_to_builtin(
                bundle_url=body.bundle_url,
                version=body.version,
                _overwrite=body.overwrite,
                cancel_checker=cancel_event.is_set,
            ),
        )
        result_payload = {
            "installed": True,
            "name": result.name,
            "enabled": result.enabled,
            "source_url": result.source_url,
        }
        if cancel_event.is_set():
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
            result=result_payload,
        )
    except SkillImportCancelled:
        await _hub_task_set_status(task_id, HubInstallTaskStatus.CANCELLED)
    except SkillScanError as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(e),
        )
    except ValueError as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(e),
        )
    except RuntimeError as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(e),
        )
    except Exception as e:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {e}",
        )
    finally:
        await _hub_task_pop_runtime(task_id)


router = APIRouter(prefix="/default-skills", tags=["default-skills"])


@router.get("")
async def list_default_skills(
    request: Request,
) -> list[DefaultSkillSpec]:
    """List all default skills (builtin and inactive)."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    all_skills = skill_service.list_all_default_skills()

    active_skills_dir = workspace_dir / "active_skills"
    active_skill_names = set()
    if active_skills_dir.exists():
        active_skill_names = {
            d.name
            for d in active_skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }

    skills_spec = [
        DefaultSkillSpec(
            name=skill.name,
            description=skill.description,
            content=skill.content,
            source=skill.source,
            path=skill.path,
            references=skill.references,
            scripts=skill.scripts,
            enabled=skill.name in active_skill_names,
        )
        for skill in all_skills
    ]

    return skills_spec


@router.post("")
async def create_default_skill(
    request_body: CreateDefaultSkillRequest,
    request: Request,
):
    """Create a new skill in builtin directory."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    result = skill_service.create_default_skill(
        name=request_body.name,
        content=request_body.content,
        references=request_body.references,
        scripts=request_body.scripts,
    )
    return {"created": result}


@router.post("/{skill_name}/enable")
async def enable_skill_in_agent(
    skill_name: str,
    request: Request = None,
):
    """Enable a default skill for current agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    if active_skill_dir.exists():
        return {"enabled": True}

    builtin_skill_dir = get_builtin_skills_dir() / skill_name
    inactive_skill_dir = get_inactive_skills_dir() / skill_name

    source_dir = None
    if builtin_skill_dir.exists():
        source_dir = builtin_skill_dir
    elif inactive_skill_dir.exists():
        source_dir = inactive_skill_dir

    if not source_dir or not (source_dir / "SKILL.md").exists():
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found",
        )

    try:
        from ...security.skill_scanner import scan_skill_directory

        scan_skill_directory(source_dir, skill_name=skill_name)
    except SkillScanError as e:
        return _scan_error_response(e)
    except Exception as scan_exc:
        logger.warning(
            "Security scan error for skill '%s' (non-fatal): %s",
            skill_name,
            scan_exc,
        )

    shutil.copytree(source_dir, active_skill_dir)

    manager = request.app.state.multi_agent_manager
    agent_id = workspace.agent_id

    async def reload_in_background():
        try:
            await manager.reload_agent(agent_id)
        except Exception as e:
            logger.warning(f"Background reload failed: {e}")

    asyncio.create_task(reload_in_background())

    return {"enabled": True}


@router.post("/{skill_name}/disable")
async def disable_skill_in_agent(
    skill_name: str,
    request: Request = None,
):
    """Disable a default skill for current agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    if active_skill_dir.exists():
        shutil.rmtree(active_skill_dir)

        manager = request.app.state.multi_agent_manager
        agent_id = workspace.agent_id

        async def reload_in_background():
            try:
                await manager.reload_agent(agent_id)
            except Exception as e:
                logger.warning(f"Background reload failed: {e}")

        asyncio.create_task(reload_in_background())

        return {"disabled": True}

    return {"disabled": False}


@router.post("/{skill_name}/move-to-inactive")
async def move_skill_to_inactive(
    skill_name: str,
    request: Request,
):
    """Move a skill from builtin to inactive directory."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    result = skill_service.move_to_inactive(skill_name)
    return {"moved": result}


@router.post("/{skill_name}/move-to-builtin")
async def move_skill_to_builtin(
    skill_name: str,
    request: Request,
):
    """Move a skill from inactive to builtin directory."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    result = skill_service.move_to_builtin(skill_name)
    return {"moved": result}


@router.delete("/{skill_name}")
async def delete_inactive_skill(
    skill_name: str,
    request: Request,
):
    """Delete a skill from inactive directory."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    result = skill_service.delete_inactive_skill(skill_name)
    return {"deleted": result}


_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@router.post("/upload")
async def upload_default_skill_zip(
    request: Request,
    file: UploadFile = File(...),
    overwrite: bool = False,
):
    """Import skill(s) to builtin directory from an uploaded zip file."""
    from ..agent_context import get_agent_for_request

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

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    try:
        result = await asyncio.to_thread(
            skill_service.import_to_builtin_from_zip,
            data,
            overwrite,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Zip skill upload failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Skill upload failed",
        ) from e

    return result


@router.post("/hub/install")
async def install_from_hub(
    request_body: HubInstallRequest,
    _request: Request,
):
    try:
        result = install_skill_from_hub_to_builtin(
            bundle_url=request_body.bundle_url,
            version=request_body.version,
            _overwrite=request_body.overwrite,
        )
    except SkillScanError as e:
        return _scan_error_response(e)
    except ValueError as e:
        detail = str(e)
        logger.warning(
            "Skill hub install 400: bundle_url=%s detail=%s",
            (request_body.bundle_url or "")[:80],
            detail,
        )
        raise HTTPException(status_code=400, detail=detail) from e
    except RuntimeError as e:
        detail = str(e)
        logger.exception(
            "Skill hub install failed (upstream/rate limit): %s",
            e,
        )
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        detail = f"Skill hub import failed: {e}"
        logger.exception("Skill hub import failed: %s", e)
        raise HTTPException(status_code=502, detail=detail) from e
    return {
        "installed": True,
        "name": result.name,
        "enabled": result.enabled,
        "source_url": result.source_url,
    }


@router.post("/hub/install/start", response_model=HubInstallTask)
async def start_install_from_hub(
    request_body: HubInstallRequest,
    _request: Request,
) -> HubInstallTask:
    task = HubInstallTask(
        bundle_url=request_body.bundle_url,
        version=request_body.version,
        overwrite=request_body.overwrite,
    )
    async with _hub_install_lock:
        _hub_install_tasks[task.task_id] = task
    cancel_event = threading.Event()
    _hub_install_cancel_events[task.task_id] = cancel_event
    runtime_task = asyncio.create_task(
        _run_hub_install_task(
            task_id=task.task_id,
            body=request_body,
            cancel_event=cancel_event,
        ),
    )
    await _hub_task_register_runtime(task.task_id, runtime_task)
    return task


@router.get("/hub/install/{task_id}", response_model=HubInstallTask)
async def get_install_status(task_id: str) -> HubInstallTask:
    task = await _hub_task_get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/hub/install/{task_id}/cancel")
async def cancel_install(task_id: str):
    task = await _hub_task_get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    cancel_event = _hub_install_cancel_events.get(task_id)
    if cancel_event is not None:
        cancel_event.set()
    return {"cancelled": True}
