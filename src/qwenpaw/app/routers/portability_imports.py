# -*- coding: utf-8 -*-
"""Agent-pinned HTTP bridge for Codex/Qoder imports."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...config.config import load_agent_config_async
from ...portability.import_jobs import PortabilityImportJobManager
from ...portability.models import ImportSelection
from ...portability.providers import provider_names, resolve_source_location
from ..auth import is_loopback_ip, is_trusted_proxy, resolve_client_ip
from ..agent_context import get_agent_for_request

portability_import_router = APIRouter(
    prefix="/portability/imports",
    tags=["portability-imports"],
)
PORTABILITY_IMPORT_JOBS = PortabilityImportJobManager()
_LOCALHOST = {"testclient"}


class CreateImportJobRequest(BaseModel):
    """Applications selected on the source step."""

    sources: list[str] = Field(min_length=1, max_length=2)


class StartImportJobRequest(BaseModel):
    """Per-source assets selected on the inventory step."""

    selections: dict[str, ImportSelection]
    allow_plugin_execution: bool = False


def _plugins_selected(selections: dict[str, ImportSelection]) -> bool:
    return any(selection.plugins for selection in selections.values())


def _local_only(request: Request) -> None:
    peer = request.client.host if request.client else ""
    if peer in _LOCALHOST:
        return
    headers = request.headers
    forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip")
    trusted_proxy = is_trusted_proxy(request)
    if forwarded and not trusted_proxy:
        raise HTTPException(
            status_code=403,
            detail="Import proxy must be trusted",
        )
    if not is_loopback_ip(resolve_client_ip(request)) or (
        not is_loopback_ip(peer)
        and (not trusted_proxy or not getattr(request.state, "user", None))
    ):
        raise HTTPException(
            status_code=403,
            detail="Import endpoints are localhost-only",
        )


def _api_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=409 if isinstance(exc, RuntimeError) else 400,
        detail=str(exc),
    )


async def _require_qwenpaw_backend(workspace) -> None:
    if (
        await load_agent_config_async(workspace.agent_id)
    ).backend != "qwenpaw":
        raise RuntimeError(
            "PawPort requires the destination Agent to use the qwenpaw "
            "backend",
        )


@portability_import_router.get("/sources")
async def list_import_sources(request: Request) -> list[dict]:
    """Report supported applications without exposing local source paths."""
    _local_only(request)
    result = []
    for source in provider_names():
        location = resolve_source_location(source)
        result.append(
            {
                "source": source,
                "name": source.title(),
                "detected": bool(
                    location.data_home_exists
                    or location.user_data_home_exists
                    or location.runtime_path,
                ),
            },
        )
    return result


@portability_import_router.post("/jobs", status_code=202)
async def create_import_job(
    body: CreateImportJobRequest,
    request: Request,
):
    """Start inventory scans for the selected applications."""
    _local_only(request)
    workspace = await get_agent_for_request(request)
    try:
        await _require_qwenpaw_backend(workspace)
        return await PORTABILITY_IMPORT_JOBS.create(workspace, body.sources)
    except (ValueError, RuntimeError) as exc:
        raise _api_error(exc) from exc


@portability_import_router.get("/jobs/current")
async def get_current_import_job(request: Request):
    """Return this agent's resumable import job, if any."""
    _local_only(request)
    workspace = await get_agent_for_request(request)
    return await PORTABILITY_IMPORT_JOBS.current(workspace)


@portability_import_router.get("/jobs/{job_id}")
async def get_import_job(job_id: str, request: Request):
    """Return the latest durable job snapshot."""
    _local_only(request)
    workspace = await get_agent_for_request(request)
    try:
        return await PORTABILITY_IMPORT_JOBS.snapshot(workspace, job_id)
    except (ValueError, RuntimeError) as exc:
        raise _api_error(exc) from exc


@portability_import_router.post("/jobs/{job_id}/start", status_code=202)
async def start_import_job(
    job_id: str,
    body: StartImportJobRequest,
    request: Request,
):
    """Apply an explicit per-source selection."""
    _local_only(request)
    workspace = await get_agent_for_request(request)
    try:
        await _require_qwenpaw_backend(workspace)
        if (
            _plugins_selected(body.selections)
            and not body.allow_plugin_execution
        ):
            raise ValueError("confirm plugin code execution before importing")
        return await PORTABILITY_IMPORT_JOBS.start(
            workspace,
            job_id,
            body.selections,
        )
    except (ValueError, RuntimeError) as exc:
        raise _api_error(exc) from exc


@portability_import_router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_import_job(
    job_id: str,
    body: StartImportJobRequest,
    request: Request,
):
    """Retry failed tools without replacing existing QwenPaw assets."""
    _local_only(request)
    workspace = await get_agent_for_request(request)
    try:
        await _require_qwenpaw_backend(workspace)
        if (
            _plugins_selected(body.selections)
            and not body.allow_plugin_execution
        ):
            raise ValueError("confirm plugin code execution before importing")
        return await PORTABILITY_IMPORT_JOBS.retry(
            workspace,
            job_id,
            body.selections,
        )
    except (ValueError, RuntimeError) as exc:
        raise _api_error(exc) from exc


@portability_import_router.post("/jobs/{job_id}/cancel")
async def cancel_import_job(job_id: str, request: Request):
    """Stop an active import or abandon an unstarted plan."""
    _local_only(request)
    workspace = await get_agent_for_request(request)
    try:
        return await PORTABILITY_IMPORT_JOBS.cancel(workspace, job_id)
    except (ValueError, RuntimeError) as exc:
        raise _api_error(exc) from exc


@portability_import_router.get("/jobs/{job_id}/events")
async def stream_import_events(
    job_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Stream reconnectable full-snapshot events."""
    _local_only(request)
    workspace = await get_agent_for_request(request)

    async def events():
        try:
            async for event in PORTABILITY_IMPORT_JOBS.subscribe(
                workspace,
                job_id,
                after=after,
            ):
                yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
        except (ValueError, RuntimeError) as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["portability_import_router"]
