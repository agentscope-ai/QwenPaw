# -*- coding: utf-8 -*-
"""Readiness probe endpoint."""

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...utils.runtime_readiness import (
    is_runtime_ready,
    runtime_failure_reason,
)

router = APIRouter(tags=["healthz"])


@router.get("/healthz")
async def get_healthz(request: Request):
    """Return 200 after core agents are ready, otherwise return 503.

    ``runtime_ready`` is a separate, stricter signal: core agents can be
    loaded while plugin projections and provider state are still being
    populated.
    """
    state = request.app.state
    ready: asyncio.Event = getattr(state, "startup_ready", None)
    if ready is None or not ready.is_set():
        return JSONResponse(
            status_code=503,
            content={
                "status": "starting",
                "detail": "Background startup in progress",
                "runtime_ready": is_runtime_ready(),
                "runtime_startup_error": runtime_failure_reason(),
            },
        )
    registry = getattr(state, "multi_agent_manager", None)
    agents = registry.list_loaded_agents() if registry else []
    start_time = getattr(state, "startup_time", None)
    uptime = round(time.time() - start_time, 2) if start_time else None
    return {
        "status": "ok",
        "agents_loaded": agents,
        "uptime_seconds": uptime,
        "runtime_ready": is_runtime_ready(),
        "runtime_startup_error": runtime_failure_reason(),
    }
