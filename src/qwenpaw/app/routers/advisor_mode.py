# -*- coding: utf-8 -*-
"""Advisor Mode API endpoints.

Provides endpoints for reading and toggling Advisor Mode per agent. The
state lives in ``agent.json`` under ``advisor_mode`` and is read by
``AgentBuilder`` on every request, so a change takes effect on the next
message without an agent reload.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..agent_context import get_agent_for_request
from ...modes.advisor.teacher import effective_teacher_slot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/advisor-mode", tags=["advisor-mode"])


class AdvisorModeUpdateRequest(BaseModel):
    """Request body for updating Advisor Mode."""

    enabled: Optional[bool] = None
    plan_enabled: Optional[bool] = None
    followup_enabled: Optional[bool] = None
    on_demand_enabled: Optional[bool] = None


def _slot(slot: object) -> dict | None:
    """``{"provider_id", "model"}`` for a configured model slot."""
    provider_id = getattr(slot, "provider_id", "") or ""
    model = getattr(slot, "model", "") or ""
    if not provider_id or not model:
        return None
    return {"provider_id": provider_id, "model": model}


def _state(config) -> dict:
    """The Advisor Mode state the Console renders."""
    am = config.advisor_mode
    return {
        "enabled": bool(am.enabled),
        "plan_enabled": bool(am.plan_enabled),
        "followup_enabled": bool(am.followup_enabled),
        "on_demand_enabled": bool(am.on_demand_enabled),
        "agent_id": config.id,
        # Teacher = the agent's main model (falling back to the global
        # active model); student = sub-agent model (None means the agent
        # keeps running on the main model).
        "teacher_model": _slot(effective_teacher_slot(config)),
        "student_model": _slot(config.subagent_model),
    }


@router.get(
    "",
    summary="Get Advisor Mode state for the current agent",
)
async def get_advisor_mode(request: Request) -> dict:
    """Return Advisor Mode state from agent.json."""
    from ...config.config import load_agent_config
    from ...utils.io_utils import run_sync_io

    workspace = await get_agent_for_request(request)
    config = await run_sync_io(load_agent_config, workspace.agent_id)
    return _state(config)


@router.post(
    "",
    summary="Enable or disable Advisor Mode for the current agent",
)
async def post_advisor_mode_update(
    body: AdvisorModeUpdateRequest,
    request: Request,
) -> dict:
    """Update Advisor Mode settings.

    Persists ``advisor_mode.enabled`` / ``followup_enabled`` /
    ``on_demand_enabled`` in ``agent.json``. Fields left out of the body
    are unchanged.
    """
    from ...config.config import update_agent_config_async

    workspace = await get_agent_for_request(request)

    def _update(config) -> None:
        if body.enabled is not None:
            config.advisor_mode.enabled = body.enabled
        if body.plan_enabled is not None:
            config.advisor_mode.plan_enabled = body.plan_enabled
        if body.followup_enabled is not None:
            config.advisor_mode.followup_enabled = body.followup_enabled
        if body.on_demand_enabled is not None:
            config.advisor_mode.on_demand_enabled = body.on_demand_enabled

    config = await update_agent_config_async(workspace.agent_id, _update)
    logger.info(
        "Advisor Mode %s for agent %s (follow-up %s)",
        "enabled" if config.advisor_mode.enabled else "disabled",
        config.id,
        "on" if config.advisor_mode.followup_enabled else "off",
    )
    return _state(config)


__all__ = ["router"]
