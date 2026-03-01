# -*- coding: utf-8 -*-
"""FastAPI routes for the approval system."""

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .models import ApprovalResponse, ApprovalStatus
from .service import ApprovalService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _get_service(request: Request) -> ApprovalService:
    svc: ApprovalService | None = getattr(
        request.app.state,
        "approval_service",
        None,
    )
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Approval service not ready",
        )
    return svc


@router.get("")
async def list_pending(request: Request):
    """List all currently pending approval requests."""
    svc = _get_service(request)
    return {"pending": [r.model_dump() for r in svc.list_pending()]}


@router.get("/{request_id}")
async def get_request(request_id: str, request: Request):
    """Get a single pending approval request by id."""
    svc = _get_service(request)
    req = svc.get_request(request_id)
    if req is None:
        raise HTTPException(
            status_code=404,
            detail="Request not found or already resolved",
        )
    return req.model_dump()


@router.post("/{request_id}")
async def respond_to_request(
    request_id: str,
    body: ApprovalResponse,
    request: Request,
):
    """Approve or deny a pending request."""
    if body.reply not in (ApprovalStatus.APPROVED, ApprovalStatus.DENIED):
        raise HTTPException(
            status_code=400,
            detail="reply must be 'approved' or 'denied'",
        )

    svc = _get_service(request)
    ok = svc.respond(request_id, body.reply)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Request not found or already resolved",
        )
    return {
        "status": "ok",
        "request_id": request_id,
        "reply": body.reply.value,
    }


@router.get("/stream/events")
async def approval_events(request: Request):
    """SSE endpoint that pushes new approval requests to the client.

    Clients connect once; each pending request is sent as a
    ``data: {json}`` frame.  A heartbeat comment is sent every 15 s
    to keep the connection alive.
    """
    svc = _get_service(request)

    async def _generate() -> AsyncGenerator[str, None]:
        seen: set[str] = set()
        while True:
            # Check for disconnect
            if await request.is_disconnected():
                break

            for req in svc.list_pending():
                if req.id not in seen:
                    seen.add(req.id)
                    payload = json.dumps(req.model_dump(), ensure_ascii=False)
                    yield f"event: approval_request\ndata: {payload}\n\n"

            # heartbeat
            yield ": heartbeat\n\n"

            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
