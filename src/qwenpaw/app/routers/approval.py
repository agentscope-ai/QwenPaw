# -*- coding: utf-8 -*-
"""Approval API endpoints for tool guard approvals."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...access.agent_repository import agent_database_id
from ...access.dependencies import get_actor
from ...identity.runtime import is_multi_user_enabled
from ..approvals import get_approval_service
from ..approvals.display import approval_display_fields
from ..agent_context import get_agent_for_request
from ..chats.access import ChatAccessDeniedError, require_conversation_access
from ...security.tool_guard.approval import ApprovalDecision, ApprovalScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approval", tags=["approval"])


class ApprovalActionRequest(BaseModel):
    """Request body for approval actions."""

    request_id: str = Field(..., description="Approval request ID (UUID)")
    session_id: str = Field(..., description="Session ID")
    conversation_id: Optional[str] = Field(
        None,
        description="PostgreSQL conversation id used for ownership validation",
    )
    user_id: Optional[str] = Field(
        None,
        description="User ID (optional, for validation)",
    )
    reason: Optional[str] = Field(
        None,
        description="Optional reason for denial",
    )
    scope: Optional[str] = Field(
        None,
        description=(
            "Approval scope for approve actions: 'exact' (record the "
            "literal target) or 'similar' (record the generalized "
            "pattern). Omitted/unknown defaults to 'exact'."
        ),
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


def _approval_user_id(request: Request) -> str | None:
    """多用户模式返回可信审批用户；Legacy 返回 ``None``。"""
    if not is_multi_user_enabled():
        return None
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return str(actor.user_id)


def _require_pending_approval_user(request: Request, pending) -> None:
    """只有审批记录指定的用户可以查看或决定该审批。"""
    approval_user_id = _approval_user_id(request)
    if approval_user_id is None:
        return
    pending_user_id = (
        getattr(pending, "approval_user_id", None)
        or getattr(pending, "user_id", None)
    )
    if pending_user_id != approval_user_id:
        raise HTTPException(status_code=404, detail="Approval not found")


async def _require_approval_write(
    request: Request,
    pending,
    requested_conversation_id: str | None,
) -> None:
    """从服务端审批记录解析会话，多用户模式只允许会话所有者。"""
    if not is_multi_user_enabled():
        return
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    workspace = await get_agent_for_request(request)
    bound_conversation_id = (getattr(pending, "extra", None) or {}).get(
        "conversation_id",
    )
    conversation_id = (
        str(bound_conversation_id).strip() if bound_conversation_id else ""
    )
    if not conversation_id:
        conversation_id = await workspace.chat_manager.get_chat_id_by_session(
            session_id=pending.root_session_id,
            channel=pending.channel,
            user_id=pending.user_id,
        )
    if not conversation_id or (
        requested_conversation_id
        and requested_conversation_id != conversation_id
    ):
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        await require_conversation_access(
            repository=workspace.chat_manager.conversation_repository,
            conversation_id=UUID(conversation_id),
            user_id=actor.user_id,
            expected_agent_id=agent_database_id(workspace.agent_id),
            write=True,
        )
    except (ValueError, ChatAccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc


@router.post(
    "/approve",
    response_model=ApprovalActionResponse,
    summary="Approve a pending tool execution",
)
async def post_approval_approve(
    request: Request,
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

    _require_pending_approval_user(request, pending)
    await _require_approval_write(request, pending, body.conversation_id)

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

    # Parse the approval scope. Unknown / omitted values fall back to None,
    # which the governance consumer treats as EXACT (least-privilege).
    scope: ApprovalScope | None = None
    if body.scope:
        try:
            scope = ApprovalScope(body.scope.strip().lower())
        except ValueError:
            logger.info(
                "Approval approve: unknown scope %r, defaulting to exact",
                body.scope,
            )
            scope = None

    # Resolve the Future
    resolved = await svc.resolve_request(
        body.request_id,
        ApprovalDecision.APPROVED,
        scope=scope,
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
    request: Request,
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

    _require_pending_approval_user(request, pending)
    await _require_approval_write(request, pending, body.conversation_id)

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
    request: Request,
    session_id: Optional[str] = None,
) -> ApprovalListResponse:
    """List all pending approval requests.

    Optionally filter by session_id.
    """
    svc = get_approval_service()

    approval_user_id = _approval_user_id(request)
    if session_id:
        logger.debug(
            "Listing approvals for root session (includes children): %s",
            session_id,
        )
    else:
        logger.debug("Listing all pending approvals")
    pending_list = await svc.list_pending_for_user(
        approval_user_id,
        root_session_id=session_id,
    )

    # Serialize pending approvals
    result = []
    for pending in pending_list:
        result.append(
            {
                "request_id": pending.request_id,
                "session_id": pending.session_id,
                "root_session_id": pending.root_session_id,
                "owner_agent_id": pending.owner_agent_id,
                "agent_id": pending.agent_id,
                "tool_name": pending.tool_name,
                **approval_display_fields(pending),
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
