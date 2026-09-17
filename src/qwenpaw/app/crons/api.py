# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from qwenpaw.exceptions import ConfigurationException

from .manager import CronManager
from .models import (
    CronDispatchTargetItem,
    CronDispatchTargetsResponse,
    CronExecutionRecord,
    CronJobSpec,
    CronJobView,
)
from ...access.actor import ActorContext
from ...access.dependencies import get_actor
from ...automation.grants import AutomationAuthorizationError

router = APIRouter(prefix="/cron", tags=["cron"])


class AutomationAuthorizeRequest(BaseModel):
    config_version: int
    authorization_digest: str


def _authorization_service(mgr: CronManager):
    service = mgr.authorization_service
    if service is None:
        return None
    return service


def _map_authorization_error(exc: AutomationAuthorizationError):
    code = str(exc)
    if code == "automation_not_found":
        return HTTPException(status_code=404, detail=code)
    if code.endswith("conflict"):
        return HTTPException(status_code=409, detail=code)
    return HTTPException(status_code=403, detail=code)


async def get_cron_manager(
    request: Request,
) -> CronManager:
    """Get cron manager for the active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    if workspace.cron_manager is None:
        raise HTTPException(
            status_code=500,
            detail="CronManager not initialized",
        )
    return workspace.cron_manager


@router.get(
    "/dispatch-targets",
    response_model=CronDispatchTargetsResponse,
)
async def list_dispatch_targets(
    request: Request,
    actor: ActorContext = Depends(get_actor),
    channel: str
    | None = Query(
        default=None,
        description="Optional channel filter",
    ),
    keyword: str
    | None = Query(
        default=None,
        description="Optional keyword for user/session/channel",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
        description="Max number of target items",
    ),
):
    """List candidate dispatch targets derived from known chats."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    chats = await workspace.chat_manager.list_chats(channel=channel)
    kw = (keyword or "").strip().lower()

    deduped: dict[tuple[str, str, str], CronDispatchTargetItem] = {}
    for chat in chats:
        if actor.user_id is not None and chat.user_id != str(actor.user_id):
            continue
        item = CronDispatchTargetItem(
            channel=chat.channel,
            user_id=chat.user_id,
            session_id=chat.session_id,
        )
        if kw:
            haystack = (
                f"{item.channel} {item.user_id} {item.session_id}".lower()
            )
            if kw not in haystack:
                continue
        deduped[(item.channel, item.user_id, item.session_id)] = item
        if len(deduped) >= limit:
            break

    items = list(deduped.values())
    channels = sorted({item.channel for item in items})
    if "console" not in channels:
        channels.insert(0, "console")
    return CronDispatchTargetsResponse(channels=channels, items=items)


@router.get("/jobs", response_model=list[CronJobSpec])
async def list_jobs(
    scope: str = Query(default="mine", pattern="^(mine|agent)$"),
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    service = _authorization_service(mgr)
    if service is None:
        return await mgr.list_jobs()
    try:
        return await service.list_visible(actor, scope=scope)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc


@router.get("/jobs/{job_id}", response_model=CronJobView)
async def get_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    service = _authorization_service(mgr)
    if service is not None:
        try:
            job = await service.require_view(actor, job_id)
        except AutomationAuthorizationError as exc:
            raise _map_authorization_error(exc) from exc
    return CronJobView(spec=job, state=mgr.get_state(job_id))


@router.post("/jobs", response_model=CronJobSpec)
async def create_job(
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    # server generates id; ignore client-provided spec.id
    job_id = str(uuid.uuid4())
    created = spec.model_copy(update={"id": job_id})
    try:
        service = _authorization_service(mgr)
        if service is None:
            await mgr.create_or_replace_job(created)
        else:
            created = await service.create(actor, created)
            await mgr.refresh_job(created.id)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
    except (ConfigurationException, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
async def replace_job(
    job_id: str,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    if spec.id is None:
        spec.id = job_id
    elif spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    try:
        service = _authorization_service(mgr)
        if service is None:
            await mgr.create_or_replace_job(spec)
        else:
            spec = await service.replace(actor, job_id, spec)
            await mgr.refresh_job(job_id)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
    except (ConfigurationException, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return spec


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    service = _authorization_service(mgr)
    try:
        ok = (
            await mgr.delete_job(job_id)
            if service is None
            else await service.delete(actor, job_id)
        )
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    try:
        service = _authorization_service(mgr)
        if service is None:
            await mgr.pause_job(job_id)
        else:
            await service.pause(actor, job_id)
            await mgr.refresh_job(job_id)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    try:
        service = _authorization_service(mgr)
        if service is None:
            await mgr.resume_job(job_id)
        else:
            await service.resume(actor, job_id)
            await mgr.refresh_job(job_id)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"resumed": True}


@router.post("/jobs/{job_id}/run")
async def run_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    try:
        service = _authorization_service(mgr)
        if service is not None:
            await service.require_modify(actor, job_id)
            await service.validate_execution(job_id)
        await mgr.run_job(job_id)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"started": True}


@router.get("/jobs/{job_id}/state")
async def get_job_state(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    service = _authorization_service(mgr)
    if service is not None:
        try:
            await service.require_view(actor, job_id)
        except AutomationAuthorizationError as exc:
            raise _map_authorization_error(exc) from exc
    return mgr.get_state(job_id).model_dump(mode="json")


@router.get("/jobs/{job_id}/history", response_model=list[CronExecutionRecord])
async def get_job_history(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    service = _authorization_service(mgr)
    if service is not None:
        try:
            await service.require_view(actor, job_id)
        except AutomationAuthorizationError as exc:
            raise _map_authorization_error(exc) from exc
    return await mgr.get_history(job_id)


@router.get("/jobs/{job_id}/authorization")
async def get_job_authorization(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    service = _authorization_service(mgr)
    if service is None:
        raise HTTPException(status_code=404, detail="automation_authorization_unavailable")
    try:
        return await service.preview(actor, job_id)
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc


@router.post("/jobs/{job_id}/authorize", response_model=CronJobSpec)
async def authorize_job(
    job_id: str,
    payload: AutomationAuthorizeRequest,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    service = _authorization_service(mgr)
    if service is None:
        raise HTTPException(status_code=404, detail="automation_authorization_unavailable")
    try:
        job = await service.authorize(
            actor,
            job_id,
            config_version=payload.config_version,
            authorization_digest=payload.authorization_digest,
        )
        await mgr.refresh_job(job_id)
        return job
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc


@router.post("/jobs/{job_id}/revoke", response_model=CronJobSpec)
async def revoke_job_authorization(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
    actor: ActorContext = Depends(get_actor),
):
    service = _authorization_service(mgr)
    if service is None:
        raise HTTPException(status_code=404, detail="automation_authorization_unavailable")
    try:
        job = await service.revoke(actor, job_id)
        await mgr.refresh_job(job_id)
        return job
    except AutomationAuthorizationError as exc:
        raise _map_authorization_error(exc) from exc
