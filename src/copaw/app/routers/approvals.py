# -*- coding: utf-8 -*-
"""Approval API for chat-integrated permission decisions."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..approvals import get_approval_service
from ...security.tool_guard.approval import ApprovalDecision

router = APIRouter(prefix="/approvals", tags=["approvals"])


class PendingApprovalResponse(BaseModel):
    """Serializable view of a pending approval."""

    request_id: str
    session_id: str
    user_id: str
    channel: str
    tool_name: str
    status: str
    created_at: float
    result_summary: str = ""
    findings_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


def _to_response(pending) -> PendingApprovalResponse:
    return PendingApprovalResponse(
        request_id=pending.request_id,
        session_id=pending.session_id,
        user_id=pending.user_id,
        channel=pending.channel,
        tool_name=pending.tool_name,
        status=pending.status,
        created_at=pending.created_at,
        result_summary=pending.result_summary,
        findings_count=pending.findings_count,
        extra=dict(pending.extra or {}),
    )


@router.get("/pending", response_model=Optional[PendingApprovalResponse])
async def get_pending_approval(
    session_id: str = Query(..., description="Chat session id"),
) -> PendingApprovalResponse | None:
    """Return the latest pending approval for a chat session, if any."""
    pending = await get_approval_service().get_pending_by_session(session_id)
    if pending is None:
        return None
    return _to_response(pending)


@router.post("/{request_id}/approve", response_model=PendingApprovalResponse)
async def approve_request(request_id: str) -> PendingApprovalResponse:
    """Approve a pending request."""
    pending = await get_approval_service().resolve_request(
        request_id,
        ApprovalDecision.APPROVED,
    )
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail="Approval request not found",
        )
    return _to_response(pending)


@router.post("/{request_id}/deny", response_model=PendingApprovalResponse)
async def deny_request(request_id: str) -> PendingApprovalResponse:
    """Deny a pending request."""
    pending = await get_approval_service().resolve_request(
        request_id,
        ApprovalDecision.DENIED,
    )
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail="Approval request not found",
        )
    return _to_response(pending)
