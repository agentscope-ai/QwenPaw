# -*- coding: utf-8 -*-
"""Retained OAuth URLs and popup contract, dispatched to the owned MCP app."""

from __future__ import annotations

import html as _html_lib
import json as _json
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..mcp.oauth_bridge import (
    start,
    callback,
    revoke,
    saved_status,
)
from ...utils.oauth_callback import managed_oauth_callback_url

router = APIRouter(prefix="/mcp", tags=["mcp-oauth"])


class OAuthStartRequest(BaseModel):
    """Request body for initiating an OAuth flow for an MCP client."""

    url: str = Field(..., description="MCP server URL")
    scope: str = Field(default="", description="OAuth scope(s) to request")
    client_id: str = Field(
        default="",
        description="Pre-registered client_id (empty → use DCR or no id)",
    )
    auth_endpoint: str = Field(
        default="",
        description="Override authorization endpoint (skips discovery)",
    )
    token_endpoint: str = Field(
        default="",
        description="Override token endpoint (skips discovery)",
    )


class OAuthStartResponse(BaseModel):
    """Response returned when an OAuth flow has been initiated."""

    auth_url: str
    session_id: str


class OAuthStatusResponse(BaseModel):
    """Current OAuth token status for an MCP client."""

    authorized: bool
    expires_at: float
    scope: str


def _redirect_uri(request: Request) -> str:
    """Return the OAuth callback URI appropriate for this request.

    Uses url_for so the /api prefix (or any other mount prefix) is
    automatically included.  Falls back to a manually constructed URL
    if url_for is unavailable (e.g. in tests).
    """
    managed_url = managed_oauth_callback_url(request)
    if managed_url:
        return managed_url
    try:
        return str(request.url_for("oauth_callback"))
    except Exception:
        base = str(request.base_url).rstrip("/")
        return f"{base}/api/mcp/oauth/callback"


def _popup_html(
    status: str,
    body_html: str,
    extra_data: Optional[dict] = None,
) -> str:
    """Return HTML for the OAuth popup callback page.

    Uses localStorage for same-origin communication so the main window
    receives the result even when window.opener is null after cross-origin
    OAuth redirects.
    """
    data: dict = {"type": "mcp-oauth", "status": status}
    if extra_data:
        data.update(extra_data)

    json_data = _json.dumps(data).replace("<", "\\u003c")

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>OAuth - QwenPaw</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont,
                   'Segoe UI', sans-serif;
      display: flex; align-items: center;
      justify-content: center;
      min-height: 100vh; margin: 0;
      background: #f8fafc;
    }}
    .card {{
      background: #fff; border-radius: 12px;
      padding: 40px 48px; text-align: center;
      box-shadow: 0 4px 24px rgba(0,0,0,.08);
      max-width: 400px;
    }}
    .close-btn {{
      margin-top: 20px; padding: 8px 28px;
      background: #4a90e2; color: #fff;
      border: none; border-radius: 6px;
      font-size: 14px; cursor: pointer;
    }}
    .close-btn:hover {{ background: #357abd; }}
  </style>
</head>
<body>
  <div class="card">
    {body_html}
    <button class="close-btn" onclick="window.close()">
      Close
    </button>
  </div>
  <script>
    (function () {{
      var data = {json_data};
      var KEY = 'mcp_oauth_result';
      try {{ localStorage.setItem(KEY, JSON.stringify(data)); }}
      catch (e) {{}}
      if (window.opener && !window.opener.closed) {{
        try {{ window.opener.postMessage(data, '*'); }}
        catch (e) {{}}
      }}
      setTimeout(function () {{ window.close(); }}, 1500);
    }})();
  </script>
</body>
</html>"""


def _make_error_page(message: str) -> HTMLResponse:
    """Return an HTML error page for the OAuth popup."""
    safe = _html_lib.escape(message)
    body = (
        "<p style='color:#c0392b;font-size:1.1em'>"
        "<strong>Authorization failed</strong></p>"
        f"<p style='color:#666;font-size:13px'>{safe}</p>"
    )
    return HTMLResponse(_popup_html("error", body), status_code=400)


@router.post(
    "/oauth/start/{client_key:path}",
    response_model=OAuthStartResponse,
)
async def oauth_start(
    client_key: str,
    body: OAuthStartRequest,
    request: Request,
) -> OAuthStartResponse:
    result = await start(
        request,
        client_key,
        {**body.model_dump(), "redirect_uri": _redirect_uri(request)},
    )
    return OAuthStartResponse(**result)


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> HTMLResponse:
    try:
        result = await callback(
            request,
            {
                "code": code,
                "state": state,
                "error": error,
                "error_description": error_description,
            },
        )
    except Exception as exc:
        return _make_error_page(str(getattr(exc, "detail", exc)))
    return HTMLResponse(
        _popup_html(
            "success",
            "<p>Authorization successful!</p>"
            "<p>This window will close shortly.</p>",
            extra_data={
                "clientKey": result["clientKey"],
                "agentId": result["agentId"],
            },
        ),
    )


@router.get(
    "/oauth/status/{client_key:path}",
    response_model=OAuthStatusResponse,
)
async def oauth_status(
    client_key: str,
    request: Request,
) -> OAuthStatusResponse:
    result = await saved_status(request, client_key)
    return OAuthStatusResponse(**result)


@router.delete("/oauth/{client_key:path}", response_model=dict)
async def oauth_revoke(client_key: str, request: Request) -> dict:
    return await revoke(request, client_key)
