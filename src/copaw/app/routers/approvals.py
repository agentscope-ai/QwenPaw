# -*- coding: utf-8 -*-
"""Channel-agnostic approval callback endpoints.

These endpoints resolve pending tool-guard approval requests regardless
of which channel originated them (console, dingtalk, etc.).

Legacy console-specific paths (``/api/console/approvals/...``) remain
in ``routers/console.py`` for backward compatibility and redirect to
the same shared ``ApprovalService``.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..approvals import get_approval_service
from ...security.tool_guard.approval import ApprovalDecision


router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/{approval_id}/approve", response_class=HTMLResponse)
async def approve_tool_call(approval_id: str):
    """Approve one pending tool-guard request (any channel)."""
    service = get_approval_service()
    pending = await service.resolve_request(
        approval_id,
        ApprovalDecision.APPROVED,
    )
    if pending is None:
        return _render_approval_result(
            title="Approval request not found",
            message=("This approval link is invalid or has already expired."),
            success=False,
        )
    return _render_approval_result(
        title="Tool approved",
        message=f"`{pending.tool_name}` can now continue execution.",
        success=True,
    )


@router.get("/{approval_id}/deny", response_class=HTMLResponse)
async def deny_tool_call(approval_id: str):
    """Deny one pending tool-guard request (any channel)."""
    service = get_approval_service()
    pending = await service.resolve_request(
        approval_id,
        ApprovalDecision.DENIED,
    )
    if pending is None:
        return _render_approval_result(
            title="Approval request not found",
            message=("This approval link is invalid or has already expired."),
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
    <html lang="en">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
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
            <div class="card">
                <h1>{title}</h1>
                <p>{message}</p>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html)
