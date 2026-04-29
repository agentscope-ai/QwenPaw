# -*- coding: utf-8 -*-
"""Progress-observing hook config API endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Request

from ...config.config import ProgressObservingConfig, save_agent_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/progress-observing", tags=["progress-observing"])


async def _get_workspace(request: Request):
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


class ProgressObservingConfigResponse(ProgressObservingConfig):
    """Response model: adds an ``enabled`` flag for the frontend toggle."""

    enabled: bool = False


@router.get(
    "/config",
    response_model=ProgressObservingConfigResponse,
    summary="Get progress-observing hook config",
)
async def get_progress_observing_config(
    request: Request,
) -> ProgressObservingConfigResponse:
    workspace = await _get_workspace(request)
    cfg = workspace.config.progress_observing
    if cfg is None:
        return ProgressObservingConfigResponse(enabled=False)
    return ProgressObservingConfigResponse(
        enabled=True,
        hook_type=cfg.hook_type,
    )


@router.put(
    "/config",
    response_model=ProgressObservingConfigResponse,
    summary="Update progress-observing hook config",
)
async def put_progress_observing_config(
    request: Request,
    body: ProgressObservingConfigResponse = Body(...),
) -> ProgressObservingConfigResponse:
    workspace = await _get_workspace(request)
    if not body.enabled:
        workspace.config.progress_observing = None
    else:
        workspace.config.progress_observing = ProgressObservingConfig(
            hook_type=body.hook_type,
        )
    save_agent_config(workspace.agent_id, workspace.config)
    cfg = workspace.config.progress_observing
    if cfg is None:
        return ProgressObservingConfigResponse(enabled=False)
    return ProgressObservingConfigResponse(
        enabled=True,
        hook_type=cfg.hook_type,
    )
