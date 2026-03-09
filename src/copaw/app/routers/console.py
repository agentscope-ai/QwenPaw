# -*- coding: utf-8 -*-
"""Console APIs for push messages and approval callbacks.

Note: the approval endpoints below are kept for backward compatibility.
New code should use the channel-agnostic ``/api/approvals/...`` endpoints
defined in ``routers/approvals.py``.
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from ..approvals import get_approval_service
from ...security.tool_guard.approval import ApprovalDecision


router = APIRouter(prefix="/console", tags=["console"])


@router.get("/push-messages")
async def get_push_messages(
    session_id: str | None = Query(None, description="Optional session id"),
):
    """
    Return pending push messages. Without session_id: recent messages
    (all sessions, last 60s), not consumed so every tab sees them.
    """
    from ..console_push_store import get_recent, take

    if session_id:
        messages = await take(session_id)
    else:
        messages = await get_recent()
    return {"messages": messages}


@router.get("/approvals/{approval_id}/approve", response_class=HTMLResponse)
async def approve_tool_call(approval_id: str):
    """Approve one pending console tool-guard request (legacy path)."""
    service = get_approval_service()
    pending = await service.resolve_request(
        approval_id,
        ApprovalDecision.APPROVED,
    )
    if pending is None:
        return _render_approval_result(
            title="Approval request not found",
            message="This approval link is invalid or has already expired.",
            success=False,
        )
    return _render_approval_result(
        title="Tool approved",
        message=f"`{pending.tool_name}` can now continue execution.",
        success=True,
    )


@router.get("/approvals/{approval_id}/deny", response_class=HTMLResponse)
async def deny_tool_call(approval_id: str):
    """Deny one pending console tool-guard request (legacy path)."""
    service = get_approval_service()
    pending = await service.resolve_request(
        approval_id,
        ApprovalDecision.DENIED,
    )
    if pending is None:
        return _render_approval_result(
            title="Approval request not found",
            message="This approval link is invalid or has already expired.",
            success=False,
        )
    return _render_approval_result(
        title="Tool denied",
        message=f"`{pending.tool_name}` will not be executed.",
        success=False,
    )


def _render_approval_result(
    *,
    title: str,
    message: str,
    success: bool,
) -> HTMLResponse:
    color = "#1677ff" if success else "#ff4d4f"
    html = f"""
        <!doctype html>
        <html lang=\"en\">
            <head>
                <meta charset=\"utf-8\" />
                <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
                <title>{title}</title>
                <style>
                    body {{
                        margin: 0;
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                        background: #f5f7fa;
                        color: #1f1f1f;
                        display: grid;
                        place-items: center;
                        min-height: 100vh;
                    }}
                    .card {{
                        width: min(560px, calc(100vw - 32px));
                        background: #fff;
                        border-radius: 16px;
                        padding: 28px;
                        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.08);
                        border-top: 4px solid {color};
                    }}
                    h1 {{ margin: 0 0 12px; font-size: 24px; }}
                    p {{ margin: 0; line-height: 1.6; white-space: pre-wrap; }}
                </style>
            </head>
            <body>
                <div class=\"card\">
                    <h1>{title}</h1>
                    <p>{message}</p>
                </div>
            </body>
        </html>
        """
    return HTMLResponse(content=html)
