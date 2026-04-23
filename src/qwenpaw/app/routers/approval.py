# -*- coding: utf-8 -*-
"""Approval API endpoints for tool guard approvals."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..approvals import get_approval_service
from ...security.tool_guard.approval import ApprovalDecision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approval", tags=["approval"])


class ApprovalActionRequest(BaseModel):
    """Request body for approval actions."""

    request_id: str = Field(..., description="Approval request ID (UUID)")
    session_id: str = Field(..., description="Session ID")
    user_id: Optional[str] = Field(
        None,
        description="User ID (optional, for validation)",
    )
    reason: Optional[str] = Field(
        None,
        description="Optional reason for denial",
    )


class ApprovalActionResponse(BaseModel):
    """Response for approval actions."""

    success: bool
    message: str
    tool_name: Optional[str] = None
    request_id: str


class ApprovalListResponse(BaseModel):
    """Response for listing pending approvals."""

    pending_approvals: list[dict]
    count: int


@router.post(
    "/approve",
    response_model=ApprovalActionResponse,
    summary="Approve a pending tool execution",
)
async def post_approval_approve(
    request: Request,  # pylint: disable=unused-argument
    body: ApprovalActionRequest,
) -> ApprovalActionResponse:
    """Approve a pending tool execution.

    Resolves the Future associated with the approval request,
    allowing the agent to continue executing the tool.
    """
    svc = get_approval_service()

    logger.info(
        "Approval approve request: request_id=%s session_id=%s",
        body.request_id[:16],
        body.session_id,
    )

    # Verify the request belongs to the root session (support cross-session)
    pending = await svc.get_request(body.request_id)
    if pending is None:
        logger.warning(
            "Approval request not found: %s",
            body.request_id[:16],
        )
        raise HTTPException(
            status_code=404,
            detail=f"Approval request not found: {body.request_id[:16]}",
        )

    if pending.root_session_id != body.session_id:
        logger.warning(
            "Root session mismatch: request %s (root: %s) not in session %s",
            body.request_id[:16],
            pending.root_session_id,
            body.session_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Root session mismatch: cannot approve other session trees",
        )

    # Resolve the Future
    resolved = await svc.resolve_request(
        body.request_id,
        ApprovalDecision.APPROVED,
    )

    logger.info(
        "Approval approved: request_id=%s session=%s tool=%s",
        body.request_id[:16],
        body.session_id,
        resolved.tool_name,
    )

    return ApprovalActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' approved, executing...",
        tool_name=resolved.tool_name,
        request_id=body.request_id,
    )


@router.post(
    "/deny",
    response_model=ApprovalActionResponse,
    summary="Deny a pending tool execution",
)
async def post_approval_deny(
    request: Request,  # pylint: disable=unused-argument
    body: ApprovalActionRequest,
) -> ApprovalActionResponse:
    """Deny a pending tool execution.

    Resolves the Future with DENIED decision, preventing
    the agent from executing the tool.
    """
    svc = get_approval_service()

    reason = body.reason or "User denied"

    logger.info(
        "Approval deny request: request_id=%s session_id=%s reason=%s",
        body.request_id[:16],
        body.session_id,
        reason,
    )

    # Verify the request belongs to the root session (support cross-session)
    pending = await svc.get_request(body.request_id)
    if pending is None:
        logger.warning(
            "Approval request not found: %s",
            body.request_id[:16],
        )
        raise HTTPException(
            status_code=404,
            detail=f"Approval request not found: {body.request_id[:16]}",
        )

    if pending.root_session_id != body.session_id:
        logger.warning(
            "Root session mismatch: request %s (root: %s) not in session %s",
            body.request_id[:16],
            pending.root_session_id,
            body.session_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Root session mismatch: cannot approve other session trees",
        )

    # Resolve the Future
    resolved = await svc.resolve_request(
        body.request_id,
        ApprovalDecision.DENIED,
    )

    logger.info(
        "Approval denied: request_id=%s session=%s tool=%s",
        body.request_id[:16],
        body.session_id,
        resolved.tool_name,
    )

    return ApprovalActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' denied: {reason}",
        tool_name=resolved.tool_name,
        request_id=body.request_id,
    )


@router.get(
    "/list",
    response_model=ApprovalListResponse,
    summary="List pending approval requests",
)
async def get_approval_list(
    request: Request,  # pylint: disable=unused-argument
    session_id: Optional[str] = None,
) -> ApprovalListResponse:
    """List all pending approval requests.

    Optionally filter by session_id.
    """
    svc = get_approval_service()

    if session_id:
        logger.debug(
            "Listing approvals for root session (includes children): %s",
            session_id,
        )
        # Use get_pending_by_root_session for cross-session support
        pending_list = await svc.get_pending_by_root_session(session_id)
    else:
        logger.debug("Listing all pending approvals")
        # pylint: disable=protected-access
        async with svc._lock:
            pending_list = list(svc._pending.values())

    # Serialize pending approvals
    result = []
    for pending in pending_list:
        result.append(
            {
                "request_id": pending.request_id,
                "session_id": pending.session_id,
                "root_session_id": pending.root_session_id,
                "agent_id": pending.agent_id,
                "tool_name": pending.tool_name,
                "severity": pending.severity,
                "findings_count": pending.findings_count,
                "created_at": pending.created_at,
                "timeout_seconds": pending.timeout_seconds,
                "result_summary": pending.result_summary,
            },
        )

    logger.info("Listed %d pending approvals", len(result))

    return ApprovalListResponse(
        pending_approvals=result,
        count=len(result),
    )
