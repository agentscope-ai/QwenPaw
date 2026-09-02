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
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request
from ...modes.advisor.teacher import (
    resolve_student_slot,
    resolve_teacher_slot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/advisor-mode", tags=["advisor-mode"])


class ModelSlotBody(BaseModel):
    """A ``{"provider_id", "model"}`` pair naming one model."""

    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)


class InterventionBody(BaseModel):
    """Partial update of the mid-run intervention thresholds."""

    consecutive_failures: Optional[int] = Field(default=None, ge=1)
    window_size: Optional[int] = Field(default=None, ge=1)
    window_failures: Optional[int] = Field(default=None, ge=1)
    cooldown_steps: Optional[int] = Field(default=None, ge=0)
    max_interventions: Optional[int] = Field(default=None, ge=0)


class AdvisorModeUpdateRequest(BaseModel):
    """Request body for updating Advisor Mode.

    Fields left out of the body are unchanged. For the two model
    overrides an explicit ``null`` clears the override (back to the
    default slot), so "omitted" and "null" mean different things.
    """

    enabled: Optional[bool] = None
    plan_enabled: Optional[bool] = None
    followup_enabled: Optional[bool] = None
    on_demand_enabled: Optional[bool] = None
    max_consults: Optional[int] = Field(default=None, ge=0)
    intervention: Optional[InterventionBody] = None
    teacher_model: Optional[ModelSlotBody] = None
    student_model: Optional[ModelSlotBody] = None


def _slot(slot: object) -> dict | None:
    """``{"provider_id", "model"}`` for a configured model slot."""
    provider_id = getattr(slot, "provider_id", "") or ""
    model = getattr(slot, "model", "") or ""
    if not provider_id or not model:
        return None
    return {"provider_id": provider_id, "model": model}


def _state(config) -> dict:
    """The Advisor Mode state the Console renders.

    ``teacher_model`` / ``student_model`` are the models actually used,
    with ``*_source`` saying where each comes from (``override`` = set in
    the Advisor tab, ``main_model`` / ``global`` = the agent's main model,
    ``subagent_model`` = the sub-agent slot). ``*_model_override`` echo the
    stored overrides so the Console can show "default" vs "custom".
    """
    am = config.advisor_mode
    teacher, teacher_source = resolve_teacher_slot(config)
    student, student_source = resolve_student_slot(config)
    return {
        "enabled": bool(am.enabled),
        "plan_enabled": bool(am.plan_enabled),
        "followup_enabled": bool(am.followup_enabled),
        "on_demand_enabled": bool(am.on_demand_enabled),
        "max_consults": int(am.max_consults),
        "intervention": am.intervention.model_dump(),
        "agent_id": config.id,
        "teacher_model": _slot(teacher),
        "teacher_source": teacher_source,
        "student_model": _slot(student),
        "student_source": student_source,
        "teacher_model_override": _slot(am.teacher_model),
        "student_model_override": _slot(am.student_model),
        # The defaults the overrides fall back to, for the Console labels.
        "main_model": _slot(
            resolve_teacher_slot(_without_overrides(config))[0],
        ),
        "subagent_model": _slot(config.subagent_model),
    }


def _without_overrides(config):
    """``config`` as seen with the advisor model overrides cleared."""
    am = config.advisor_mode.model_copy(
        update={"teacher_model": None, "student_model": None},
    )
    return config.model_copy(update={"advisor_mode": am})


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

    Persists the ``advisor_mode`` section of ``agent.json``: the switches,
    ``max_consults`` and the two model overrides. Fields left out of the
    body are unchanged; ``"teacher_model": null`` / ``"student_model":
    null`` clear the respective override.
    """
    from ...config.config import ModelSlotConfig, update_agent_config_async

    workspace = await get_agent_for_request(request)
    given = body.model_fields_set

    def _slot_config(slot: Optional[ModelSlotBody]):
        if slot is None:
            return None
        return ModelSlotConfig(provider_id=slot.provider_id, model=slot.model)

    def _update(config) -> None:
        am = config.advisor_mode
        if body.enabled is not None:
            am.enabled = body.enabled
        if body.plan_enabled is not None:
            am.plan_enabled = body.plan_enabled
        if body.followup_enabled is not None:
            am.followup_enabled = body.followup_enabled
        if body.on_demand_enabled is not None:
            am.on_demand_enabled = body.on_demand_enabled
        if body.max_consults is not None:
            am.max_consults = body.max_consults
        if body.intervention is not None:
            am.intervention = am.intervention.model_copy(
                update=body.intervention.model_dump(exclude_none=True),
            )
        if "teacher_model" in given:
            am.teacher_model = _slot_config(body.teacher_model)
        if "student_model" in given:
            am.student_model = _slot_config(body.student_model)

    config = await update_agent_config_async(workspace.agent_id, _update)
    logger.info(
        "Advisor Mode %s for agent %s (follow-up %s)",
        "enabled" if config.advisor_mode.enabled else "disabled",
        config.id,
        "on" if config.advisor_mode.followup_enabled else "off",
    )
    return _state(config)


__all__ = ["router"]
