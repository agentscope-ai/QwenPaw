# -*- coding: utf-8 -*-
"""Coding Mode API endpoints.

Provides endpoints for reading and toggling Coding Mode per agent.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..agent_context import get_agent_for_request
from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding-mode", tags=["coding-mode"])


class CodingModeToggleRequest(BaseModel):
    """Request body for toggling Coding Mode."""

    enabled: bool


@router.get(
    "",
    summary="Get Coding Mode state for the current agent",
)
async def get_coding_mode(request: Request) -> dict:
    """Return Coding Mode state from agent.json.

    Frontend calls this on agent switch / app boot so the UI state
    (toggle label, IDE layout) tracks the backend instead of stale
    browser cache.
    """
    import asyncio
    from ...config.config import load_agent_config

    workspace = await get_agent_for_request(request)
    loop = asyncio.get_running_loop()
    config = await loop.run_in_executor(
        None,
        load_agent_config,
        workspace.agent_id,
    )
    cm = config.coding_mode
    return {
        "enabled": bool(cm.enabled),
        "project_dir": cm.project_dir,
        "agent_id": config.id,
    }


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

    loop = asyncio.get_running_loop()
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

    # Reload the agent so the new coding_mode.enabled value is picked up:
    # CodingModeMixin._coding_mode_enabled() reads the in-memory
    # _agent_config (not hot-reloaded), and the lsp / ast_search tools
    # are only wired in _create_toolkit at construction time.
    schedule_agent_reload(request, config.id)

    logger.info(
        "Coding Mode %s for agent %s",
        "enabled" if body.enabled else "disabled",
        config.id,
    )
    return {
        "enabled": body.enabled,
        "agent_id": config.id,
    }
