# -*- coding: utf-8 -*-
"""Queryable Creator traces and workspace-owned observability settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query

from schemas.observability import ObservabilityConfigData
from services.observability import (
    load_observability_config,
    read_trace_records,
    save_observability_config,
)

from .dependencies import CreatorErrorRoute, resolve_idempotency_key


router = APIRouter(
    prefix="/observability",
    tags=["creator-observability"],
    route_class=CreatorErrorRoute,
)


@router.get("/config", response_model=ObservabilityConfigData)
async def get_observability_config() -> ObservabilityConfigData:
    return load_observability_config()


@router.put("/config", response_model=ObservabilityConfigData)
async def put_observability_config(
    config: ObservabilityConfigData,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> ObservabilityConfigData:
    resolve_idempotency_key(idempotency_key)
    save_observability_config(config)
    return load_observability_config()


@router.get("/traces")
async def query_observability_traces(
    trace_id: str | None = Query(None, alias="traceId"),
    error_id: str | None = Query(None, alias="errorId"),
    request_id: str | None = Query(None, alias="requestId"),
    project_id: str | None = Query(None, alias="projectId"),
    session_id: str | None = Query(None, alias="sessionId"),
    run_id: str | None = Query(None, alias="runId"),
    task_id: str | None = Query(None, alias="taskId"),
    name: str | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=2_000),
) -> dict[str, Any]:
    values = {
        "traceId": trace_id,
        "errorId": error_id,
        "requestId": request_id,
        "projectId": project_id,
        "sessionId": session_id,
        "runId": run_id,
        "taskId": task_id,
        "name": name,
        "status": status,
    }
    filters = {key: value for key, value in values.items() if value}
    records = read_trace_records(filters=filters, limit=limit)
    return {"items": records, "count": len(records), "limit": limit}


__all__ = ["router"]
