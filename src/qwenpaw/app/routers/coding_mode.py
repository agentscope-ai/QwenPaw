# -*- coding: utf-8 -*-
"""Coding Mode API endpoints.

Provides endpoints for toggling Coding Mode on/off per agent and for
resolving inline diff approval decisions.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding-mode", tags=["coding-mode"])


class CodingModeToggleRequest(BaseModel):
    """Request body for toggling Coding Mode."""

    enabled: bool


class DiffApprovalRequest(BaseModel):
    """Request body for approving or rejecting a diff preview."""

    decision: str  # "approve" | "reject"


@router.post(
    "",
    summary="Enable or disable Coding Mode for the current agent",
)
async def post_coding_mode_toggle(
    body: CodingModeToggleRequest,
    request: Request,
) -> dict:
    """Toggle Coding Mode on or off.

    Persists the setting in ``agent.json`` under ``coding_mode.enabled``
    and also enables / disables the ``todo_write`` tool accordingly.

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
    config.coding_mode.todo_write_enabled = body.enabled

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


@router.post(
    "/diff-approval/{approval_id}",
    summary="Approve or reject an inline diff preview",
)
async def post_diff_approval(
    approval_id: str,
    body: DiffApprovalRequest,
    request: Request,  # pylint: disable=unused-argument
) -> dict:
    """Resolve a pending diff approval request.

    This is called by the frontend after the user clicks
    "Approve" or "Reject" in the DiffApprovalModal.

    Args:
        approval_id: UUID of the pending approval created by
            ``CodingModeMixin._diff_guarded_acting``.
        body: ``{"decision": "approve" | "reject"}``

    Returns:
        ``{"success": true, "decision": "approve" | "reject"}``
    """
    from ..diff_approvals import get_diff_approval_service

    decision_str = (body.decision or "").strip().lower()
    if decision_str not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid decision '{body.decision}'. "
            "Must be 'approve' or 'reject'.",
        )

    svc = get_diff_approval_service()
    success = await svc.resolve(approval_id, decision_str)

    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Approval request '{approval_id}' not found or "
            "already resolved.",
        )

    return {
        "success": True,
        "approval_id": approval_id,
        "decision": decision_str,
    }
