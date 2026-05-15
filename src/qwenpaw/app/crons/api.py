# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .manager import CronManager
from .models import (
    CronDispatchTargetItem,
    CronDispatchTargetsResponse,
    CronExecutionRecord,
    CronJobSpec,
    CronJobView,
)

router = APIRouter(prefix="/cron", tags=["cron"])


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
async def list_jobs(mgr: CronManager = Depends(get_cron_manager)):
    return await mgr.list_jobs()


@router.get("/jobs/{job_id}", response_model=CronJobView)
async def get_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return CronJobView(spec=job, state=mgr.get_state(job_id))


@router.post("/jobs", response_model=CronJobSpec)
async def create_job(
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    # server generates id; ignore client-provided spec.id
    job_id = str(uuid.uuid4())
    created = spec.model_copy(update={"id": job_id})
    await mgr.create_or_replace_job(created)
    return created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
async def replace_job(
    job_id: str,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    if spec.id is None:
        spec.id = job_id
    elif spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    await mgr.create_or_replace_job(spec)
    return spec


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    ok = await mgr.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    try:
        await mgr.pause_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    try:
        await mgr.resume_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"resumed": True}


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, mgr: CronManager = Depends(get_cron_manager)):
    try:
        await mgr.run_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"started": True}


@router.get("/jobs/{job_id}/state")
async def get_job_state(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return mgr.get_state(job_id).model_dump(mode="json")


@router.get("/jobs/{job_id}/history", response_model=list[CronExecutionRecord])
async def get_job_history(
    job_id: str,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return await mgr.get_history(job_id)
