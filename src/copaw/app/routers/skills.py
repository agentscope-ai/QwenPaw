# -*- coding: utf-8 -*-
import asyncio
import logging
import threading
import time
import uuid
from enum import Enum
from typing import Any
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from ...agents.skills_manager import (
    SkillService,
    SkillInfo,
)
from ...agents.skills_hub import (
    SkillImportCancelled,
    search_hub_skills,
    install_skill_from_hub,
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


class SkillSpec(SkillInfo):
    enabled: bool = False


class CreateSkillRequest(BaseModel):
    name: str = Field(..., description="Skill name")
    content: str = Field(..., description="Skill content (SKILL.md)")
    references: dict[str, Any] | None = Field(
        None,
        description="Optional tree structure for references/. "
        "Can be flat {filename: content} or nested "
        "{dirname: {filename: content}}",
    )
    scripts: dict[str, Any] | None = Field(
        None,
        description="Optional tree structure for scripts/. "
        "Can be flat {filename: content} or nested "
        "{dirname: {filename: content}}",
    )


class HubSkillSpec(BaseModel):
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    enable: bool = Field(default=True, description="Enable after import")
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing customized skill",
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
    enable: bool = True
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


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills(
    request: Request,
) -> list[SkillSpec]:
    """List all skills for active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    # Get all skills (builtin + customized)
    all_skills = skill_service.list_all_skills()

    # Get active skills to determine enabled status
    active_skills_dir = workspace_dir / "active_skills"
    active_skill_names = set()
    if active_skills_dir.exists():
        active_skill_names = {
            d.name
            for d in active_skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }

    # Convert to SkillSpec with enabled status
    skills_spec = [
        SkillSpec(
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


@router.get("/available")
async def get_available_skills(
    request: Request,
) -> list[SkillSpec]:
    """List available (enabled) skills for active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    # Get available (active) skills
    available_skills = skill_service.list_available_skills()

    # Convert to SkillSpec
    skills_spec = [
        SkillSpec(
            name=skill.name,
            description=skill.description,
            content=skill.content,
            source=skill.source,
            path=skill.path,
            references=skill.references,
            scripts=skill.scripts,
            enabled=True,
        )
        for skill in available_skills
    ]

    return skills_spec


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


def _github_token_hint(bundle_url: str) -> str:
    """Hint to set GITHUB_TOKEN when URL is from GitHub/skills.sh."""
    if not bundle_url:
        return ""
    lower = bundle_url.lower()
    if "skills.sh" in lower or "github.com" in lower:
        return " Tip: set GITHUB_TOKEN (or GH_TOKEN) to avoid rate limits."
    return ""


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


def _cleanup_imported_skill(workspace_dir: Path, skill_name: str) -> None:
    """Best-effort cleanup for cancelled skill imports."""
    if not skill_name:
        return
    try:
        skill_service = SkillService(workspace_dir)
        skill_service.disable_skill(skill_name)
        skill_service.delete_skill(skill_name)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(
            "Cleanup after cancelled import failed for '%s': %s",
            skill_name,
            e,
        )


async def _run_hub_install_task(
    *,
    task_id: str,
    workspace_dir: Path,
    body: HubInstallRequest,
    cancel_event: threading.Event,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    result_payload: dict[str, Any] | None = None
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
        result_payload = {
            "installed": True,
            "name": result.name,
            "enabled": result.enabled,
            "source_url": result.source_url,
        }
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
            result=result_payload,
        )
    except SkillImportCancelled:
        if imported_skill_name:
            _cleanup_imported_skill(workspace_dir, imported_skill_name)
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
            error=str(e) + _github_token_hint(body.bundle_url),
        )
    except Exception as e:  # pylint: disable=broad-except
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {e}"
            + _github_token_hint(body.bundle_url),
        )
    finally:
        await _hub_task_pop_runtime(task_id)


@router.post("/hub/install")
async def install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)

    try:
        result = install_skill_from_hub(
            workspace_dir=workspace_dir,
            bundle_url=request_body.bundle_url,
            version=request_body.version,
            enable=request_body.enable,
            overwrite=request_body.overwrite,
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
        detail = str(e) + _github_token_hint(request_body.bundle_url)
        logger.exception(
            "Skill hub install failed (upstream/rate limit): %s",
            e,
        )
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        detail = f"Skill hub import failed: {e}" + _github_token_hint(
            request_body.bundle_url,
        )
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
    request: Request,
) -> HubInstallTask:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
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


_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


@router.post("/upload")
async def upload_skill_zip(
    request: Request,
    file: UploadFile = File(...),
    enable: bool = False,
    overwrite: bool = False,
):
    """Import skill(s) from an uploaded zip file."""
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
            skill_service.import_from_zip,
            data,
            overwrite,
            enable,
        )
    except SkillScanError as e:
        return _scan_error_response(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Zip skill upload failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Skill upload failed",
        ) from e

    return result


@router.post("/batch-disable")
async def batch_disable_skills(
    skill_name: list[str],
    request: Request,
) -> None:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    for skill in skill_name:
        skill_service.disable_skill(skill)


@router.post("/batch-enable")
async def batch_enable_skills(
    skill_name: list[str],
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    blocked: list[dict] = []
    for skill in skill_name:
        try:
            skill_service.enable_skill(skill)
        except SkillScanError as e:
            blocked.append(
                {
                    "skill_name": skill,
                    "max_severity": e.result.max_severity.value,
                    "detail": str(e),
                },
            )
    if blocked:
        return JSONResponse(
            status_code=422,
            content={
                "type": "security_scan_failed",
                "detail": (
                    f"{len(blocked)} skill(s) blocked by security scan"
                ),
                "blocked_skills": blocked,
            },
        )


@router.post("")
async def create_skill(
    request_body: CreateSkillRequest,
    request: Request,
):
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    try:
        result = skill_service.create_skill(
            name=request_body.name,
            content=request_body.content,
            references=request_body.references,
            scripts=request_body.scripts,
        )
    except SkillScanError as e:
        return _scan_error_response(e)
    return {"created": result}


@router.post("/{skill_name}/disable")
async def disable_skill(
    skill_name: str,
    request: Request = None,
):
    """Disable skill for active agent."""
    from ..agent_context import get_agent_for_request
    import shutil

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    if active_skill_dir.exists():
        shutil.rmtree(active_skill_dir)

        # Hot reload config (async, non-blocking)
        # IMPORTANT: Get manager and agent_id before creating background task
        # to avoid accessing request/workspace after their lifecycle ends
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


@router.post("/{skill_name}/enable")
async def enable_skill(
    skill_name: str,
    request: Request = None,
):
    """Enable skill for active agent."""
    from ..agent_context import get_agent_for_request
    import shutil

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    active_skill_dir = workspace_dir / "active_skills" / skill_name

    # If already enabled, skip
    if active_skill_dir.exists():
        return {"enabled": True}

    # Find skill from builtin or customized
    builtin_skill_dir = (
        Path(__file__).parent.parent.parent / "agents" / "skills" / skill_name
    )
    customized_skill_dir = workspace_dir / "customized_skills" / skill_name

    source_dir = None
    if customized_skill_dir.exists():
        source_dir = customized_skill_dir
    elif builtin_skill_dir.exists():
        source_dir = builtin_skill_dir

    if not source_dir or not (source_dir / "SKILL.md").exists():
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found",
        )

    # --- Security scan (pre-activation) --------------------------------
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
    # -------------------------------------------------------------------

    # Copy to active_skills
    shutil.copytree(source_dir, active_skill_dir)

    # Hot reload config (async, non-blocking)
    # IMPORTANT: Get manager and agent_id before creating background task
    # to avoid accessing request/workspace after their lifecycle ends
    manager = request.app.state.multi_agent_manager
    agent_id = workspace.agent_id

    async def reload_in_background():
        try:
            await manager.reload_agent(agent_id)
        except Exception as e:
            logger.warning(f"Background reload failed: {e}")

    asyncio.create_task(reload_in_background())

    return {"enabled": True}


@router.delete("/{skill_name}")
async def delete_skill(
    skill_name: str,
    request: Request,
):
    """Delete a skill from customized_skills directory permanently.

    This only deletes skills from customized_skills directory.
    Built-in skills cannot be deleted.
    """
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    result = skill_service.delete_skill(skill_name)
    return {"deleted": result}


@router.get("/{skill_name}/files/{source}/{file_path:path}")
async def load_skill_file(
    skill_name: str,
    source: str,
    file_path: str,
    request: Request,
):
    """Load a specific file from a skill's references or scripts directory.

    Args:
        skill_name: Name of the skill
        source: Source directory ("builtin" or "customized")
        file_path: Path relative to skill directory, must start with
                   "references/" or "scripts/"

    Returns:
        File content as string, or None if not found

        Example:

            GET /skills/my_skill/files/customized/references/doc.md

            GET /skills/builtin_skill/files/builtin/scripts/utils/helper.py

    """
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    skill_service = SkillService(workspace_dir)

    content = skill_service.load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
        source=source,
    )
    return {"content": content}
