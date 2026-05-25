# -*- coding: utf-8 -*-
"""Coding Mode API endpoints.

Provides an endpoint for toggling Coding Mode on/off per agent.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding-mode", tags=["coding-mode"])


class CodingModeToggleRequest(BaseModel):
    """Request body for toggling Coding Mode."""

    enabled: bool


@router.post(
    "",
    summary="Enable or disable Coding Mode for the current agent",
)
async def post_coding_mode_toggle(
    body: CodingModeToggleRequest,
    request: Request,
) -> dict:
    """Toggle Coding Mode on or off.

    Persists the setting in ``agent.json`` under ``coding_mode.enabled``.

    Returns:
        Dict with ``enabled`` field reflecting the new state.
    """
    import asyncio
    from ...config.config import load_agent_config, save_agent_config

    workspace = await get_agent_for_request(request)

    loop = asyncio.get_event_loop()
    config = await loop.run_in_executor(
        None,
        load_agent_config,
        workspace.agent_id,
    )

    config.coding_mode.enabled = body.enabled

    await loop.run_in_executor(
        None,
        save_agent_config,
        config.id,
        config,
    )

    logger.info(
        "Coding Mode %s for agent %s",
        "enabled" if body.enabled else "disabled",
        config.id,
    )
    return {
        "enabled": body.enabled,
        "agent_id": config.id,
    }
