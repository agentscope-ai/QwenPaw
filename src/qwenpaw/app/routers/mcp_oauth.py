# -*- coding: utf-8 -*-
"""OAuth 2.1 authorization endpoints for remote MCP clients.

Implements RFC 8414 (Authorization Server Metadata), RFC 9728
(Protected Resource Metadata), and PKCE (RFC 7636) for interactive
browser-based OAuth flows triggered from the frontend.
"""

from __future__ import annotations

import base64
import hashlib
import html as _html_lib
import json as _json
import logging
import secrets
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..utils import schedule_agent_reload
from ...config.config import MCPOAuthConfig, save_agent_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp-oauth"])

# ---------------------------------------------------------------------------
# In-memory state store: state_token -> OAuthSession (TTL 10 min)
# ---------------------------------------------------------------------------

_TTL_SECONDS = 600


class OAuthSession:
    """Transient server-side state for a single OAuth round-trip."""

    def __init__(
        self,
        agent_id: str,
        client_key: str,
        code_verifier: str,
        client_id: str,
        auth_endpoint: str,
        token_endpoint: str,
        redirect_uri: str,
        scope: str,
    ) -> None:
        """Initialise OAuth session."""
        self.agent_id = agent_id
        self.client_key = client_key
        self.code_verifier = code_verifier
        self.client_id = client_id
        self.auth_endpoint = auth_endpoint
        self.token_endpoint = token_endpoint
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.created_at = time.monotonic()

    def is_expired(self) -> bool:
        """Return True if this session has exceeded the TTL."""
        return (time.monotonic() - self.created_at) > _TTL_SECONDS


_state_store: Dict[str, OAuthSession] = {}


def _purge_expired() -> None:
    """Remove expired sessions (called opportunistically)."""
    expired = [k for k, v in _state_store.items() if v.is_expired()]
    for k in expired:
        del _state_store[k]


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _generate_code_verifier() -> str:
    """Generate a cryptographically random PKCE code_verifier (RFC 7636)."""
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    )


def _code_challenge(verifier: str) -> str:
    """Derive S256 code_challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# OAuth metadata discovery helpers
# ---------------------------------------------------------------------------


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
) -> Optional[dict]:
    """Fetch JSON from url; return None on any error."""
    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"OAuth metadata fetch failed for {url}: {exc}")
    return None


async def _probe_resource_metadata_url(
    client: httpx.AsyncClient,
    mcp_url: str,
) -> Optional[str]:
    """Return resource_metadata URL from 401 WWW-Authenticate header."""
    try:
        resp = await client.get(mcp_url, timeout=10.0)
        if resp.status_code != 401:
            return None
        www_auth = resp.headers.get("www-authenticate", "")
        for part in www_auth.split(","):
            if "resource_metadata=" in part.lower():
                return part.split("=", 1)[1].strip().strip('"')
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"MCP probe failed for {mcp_url}: {exc}")
    return None


async def _resolve_auth_server_url(
    client: httpx.AsyncClient,
    mcp_url: str,
) -> Optional[str]:
    """Return the authorization-server URL from PRM discovery."""
    # Try 401 header first
    rm_url = await _probe_resource_metadata_url(client, mcp_url)
    if rm_url:
        prm = await _fetch_json(client, rm_url)
        if prm and "authorization_servers" in prm:
            return prm["authorization_servers"][0]

    # Fall back to well-known PRM paths
    parsed = urlparse(mcp_url.rstrip("/"))
    root = f"{parsed.scheme}://{parsed.netloc}"
    path_suffix = parsed.path.lstrip("/")
    candidates = [
        f"{root}/.well-known/oauth-protected-resource/{path_suffix}"
        if path_suffix
        else None,
        f"{root}/.well-known/oauth-protected-resource",
    ]
    for url in candidates:
        if not url:
            continue
        prm = await _fetch_json(client, url)
        if prm and "authorization_servers" in prm:
            return prm["authorization_servers"][0]
    return None


async def _fetch_as_metadata(
    client: httpx.AsyncClient,
    auth_server_url: str,
) -> Optional[dict]:
    """Fetch authorization-server metadata via RFC 8414 / OIDC discovery."""
    parsed_as = urlparse(auth_server_url.rstrip("/"))
    as_root = f"{parsed_as.scheme}://{parsed_as.netloc}"
    as_path = parsed_as.path.lstrip("/")
    if as_path:
        candidates = [
            f"{as_root}/.well-known/oauth-authorization-server/{as_path}",
            f"{as_root}/.well-known/openid-configuration/{as_path}",
            f"{auth_server_url}/.well-known/openid-configuration",
        ]
    else:
        candidates = [
            f"{as_root}/.well-known/oauth-authorization-server",
            f"{as_root}/.well-known/openid-configuration",
        ]
    for url in candidates:
        meta = await _fetch_json(client, url)
        if meta and "authorization_endpoint" in meta:
            return meta
    return None


async def _discover_oauth_metadata(
    mcp_url: str,
) -> Tuple[str, str, Optional[str]]:
    """Discover OAuth endpoints via RFC 9728 + RFC 8414 / OIDC discovery.

    Args:
        mcp_url: Remote MCP server URL

    Returns:
        (authorization_endpoint, token_endpoint, registration_endpoint|None)

    Raises:
        HTTPException(400) on discovery failure.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        auth_server_url = await _resolve_auth_server_url(client, mcp_url)
        if not auth_server_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not discover OAuth authorization server for this "
                    "MCP endpoint. The server may not expose Protected "
                    "Resource Metadata (RFC 9728). "
                    "Please enter auth_endpoint and token_endpoint manually."
                ),
            )

        as_meta = await _fetch_as_metadata(client, auth_server_url)
        if not as_meta or "authorization_endpoint" not in as_meta:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not retrieve authorization server metadata from "
                    f"{auth_server_url}. "
                    "Please enter auth_endpoint and token_endpoint manually."
                ),
            )

        if "token_endpoint" not in as_meta:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Authorization server metadata from {auth_server_url} "
                    "is missing 'token_endpoint'. "
                    "Please enter auth_endpoint and token_endpoint manually."
                ),
            )

        return (
            as_meta["authorization_endpoint"],
            as_meta["token_endpoint"],
            as_meta.get("registration_endpoint"),
        )


async def _dynamic_register(
    registration_endpoint: str,
    redirect_uri: str,
) -> Optional[str]:
    """Attempt Dynamic Client Registration (RFC 7591); return client_id."""
    payload = {
        "client_name": "QwenPaw MCP Client",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                registration_endpoint,
                json=payload,
                timeout=10.0,
            )
            if resp.status_code in (200, 201):
                return resp.json().get("client_id")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Dynamic client registration failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helper: derive redirect_uri from current request
# ---------------------------------------------------------------------------


def _redirect_uri(request: Request) -> str:
    """Return the OAuth callback URI appropriate for this request.

    Uses url_for so the /api prefix (or any other mount prefix) is
    automatically included.  Falls back to a manually constructed URL
    if url_for is unavailable (e.g. in tests).
    """
    try:
        return str(request.url_for("oauth_callback"))
    except Exception:  # noqa: BLE001
        base = str(request.base_url).rstrip("/")
        return f"{base}/api/mcp/oauth/callback"


# ---------------------------------------------------------------------------
# HTML popup helpers
# ---------------------------------------------------------------------------


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

    json_data = _json.dumps(data)

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{client_key}/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    client_key: str,
    body: OAuthStartRequest,
    request: Request,
) -> OAuthStartResponse:
    """Start an interactive OAuth 2.1 PKCE flow for an MCP client.

    Discovers OAuth endpoints, generates PKCE parameters, optionally
    performs Dynamic Client Registration, and returns the authorization
    URL for the frontend to open in a browser popup.
    """
    from ..agent_context import get_agent_for_request

    _purge_expired()

    # -- Validate agent exists and is enabled -----------------------------
    agent = await get_agent_for_request(request)
    agent_id = agent.agent_id

    redirect_uri = _redirect_uri(request)

    # -- Resolve endpoints -------------------------------------------------
    if body.auth_endpoint and body.token_endpoint:
        auth_endpoint = body.auth_endpoint
        token_endpoint = body.token_endpoint
        registration_endpoint: Optional[str] = None
    else:
        (
            auth_endpoint,
            token_endpoint,
            registration_endpoint,
        ) = await _discover_oauth_metadata(body.url)

    # -- Resolve client_id -------------------------------------------------
    client_id = body.client_id
    if not client_id and registration_endpoint:
        client_id = (
            await _dynamic_register(registration_endpoint, redirect_uri) or ""
        )

    # -- PKCE --------------------------------------------------------------
    verifier = _generate_code_verifier()
    challenge = _code_challenge(verifier)
    state = secrets.token_hex(16)

    # -- Store session -----------------------------------------------------
    _state_store[state] = OAuthSession(
        agent_id=agent_id,
        client_key=client_key,
        code_verifier=verifier,
        client_id=client_id,
        auth_endpoint=auth_endpoint,
        token_endpoint=token_endpoint,
        redirect_uri=redirect_uri,
        scope=body.scope,
    )

    # -- Build authorization URL ------------------------------------------
    params: dict = {
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if client_id:
        params["client_id"] = client_id
    if body.scope:
        params["scope"] = body.scope

    auth_url = f"{auth_endpoint}?{urlencode(params)}"

    return OAuthStartResponse(auth_url=auth_url, session_id=state)


def _make_error_page(message: str) -> HTMLResponse:
    """Return an HTML error page for the OAuth popup."""
    safe = _html_lib.escape(message)
    body = (
        "<p style='color:#c0392b;font-size:1.1em'>"
        "<strong>Authorization failed</strong></p>"
        f"<p style='color:#666;font-size:13px'>{safe}</p>"
    )
    return HTMLResponse(_popup_html("error", body), status_code=400)


async def _exchange_code_for_tokens(
    session: OAuthSession,
    code: str,
) -> dict:
    """Exchange an authorization code for tokens.

    Returns the raw token dict on success.
    Raises ValueError with a human-readable message on failure.
    """
    token_data: dict = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": session.redirect_uri,
        "code_verifier": session.code_verifier,
    }
    if session.client_id:
        token_data["client_id"] = session.client_id

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                session.token_endpoint,
                data=token_data,
                timeout=15.0,
            )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Token exchange request failed: {exc}") from exc

    if resp.status_code not in (200, 201):
        raise ValueError(
            f"Token exchange failed (HTTP {resp.status_code}): "
            f"{resp.text[:300]}",
        )
    return resp.json()


async def _persist_tokens(
    request: Request,
    session: OAuthSession,
    tokens: dict,
) -> None:
    """Persist OAuth tokens into the MCP client's agent.json config.

    Raises ValueError with a human-readable message on failure.
    """
    access_token: str = tokens.get("access_token", "")
    if not access_token:
        raise ValueError("Token response did not contain an access_token.")

    refresh_token: str = tokens.get("refresh_token", "")
    expires_in: int = int(tokens.get("expires_in", 3600))
    expires_at: float = time.time() + expires_in
    scope: str = tokens.get("scope", session.scope)

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise ValueError("MultiAgentManager not initialised")

    # Fallback to active agent if agent_id was not captured at oauth_start
    agent_id = session.agent_id
    if not agent_id:
        from ...config.utils import load_config

        cfg = load_config()
        agent_id = cfg.agents.active_agent or "default"

    workspace = await manager.get_agent(agent_id)
    mcp_cfg = workspace.config.mcp
    client_cfg = mcp_cfg.clients.get(session.client_key) if mcp_cfg else None
    if client_cfg is None:
        raise ValueError(
            f"MCP client '{session.client_key}' not found. "
            "Please create the client first, then re-authorize.",
        )

    existing_oauth = client_cfg.oauth or MCPOAuthConfig()
    client_cfg.oauth = MCPOAuthConfig(
        client_id=session.client_id or existing_oauth.client_id,
        scope=scope,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        token_endpoint=session.token_endpoint,
        auth_endpoint=session.auth_endpoint or existing_oauth.auth_endpoint,
    )
    save_agent_config(agent_id, workspace.config)
    schedule_agent_reload(request, agent_id)


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> HTMLResponse:
    """Handle the OAuth 2.1 authorization code callback.

    Exchanges the authorization code for tokens, writes them into the
    MCP client's OAuth config in agent.json, then returns HTML that
    notifies the opener popup window and closes itself.
    """
    _purge_expired()

    if error:
        return _make_error_page(error_description or error)

    if not code or not state:
        return _make_error_page("Missing 'code' or 'state' parameter.")

    session = _state_store.get(state)
    if session is None or session.is_expired():
        return _make_error_page(
            "OAuth session expired or not found. Please try again.",
        )

    try:
        tokens = await _exchange_code_for_tokens(session, code)
        await _persist_tokens(request, session, tokens)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"OAuth callback failed for '{session.client_key}': {exc}",
            exc_info=True,
        )
        detail = getattr(exc, "detail", str(exc))
        return _make_error_page(str(detail))

    _state_store.pop(state, None)

    success_body = (
        "<p style='color:#27ae60;font-size:1.8em;margin:0'>&#10003;</p>"
        "<p style='font-size:1.1em;font-weight:600;margin:8px 0 4px'>"
        "Authorization successful!</p>"
        "<p style='color:#888;font-size:13px'>"
        "This window will close shortly.</p>"
    )
    return HTMLResponse(
        _popup_html(
            "success",
            success_body,
            extra_data={
                "clientKey": session.client_key,
                "agentId": session.agent_id,
            },
        ),
    )


@router.get(
    "/{client_key}/oauth/status",
    response_model=OAuthStatusResponse,
)
async def oauth_status(
    client_key: str,
    request: Request,
) -> OAuthStatusResponse:
    """Return the current OAuth token status for an MCP client."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    mcp_config = agent.config.mcp
    client_cfg = mcp_config.clients.get(client_key) if mcp_config else None
    if client_cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"MCP client '{client_key}' not found",
        )

    oauth = client_cfg.oauth
    if not oauth or not oauth.access_token:
        return OAuthStatusResponse(
            authorized=False,
            expires_at=0.0,
            scope="",
        )

    # Token is valid only when not expired (expires_at=0 means no expiry set)
    not_expired = oauth.expires_at <= 0 or oauth.expires_at > time.time()
    return OAuthStatusResponse(
        authorized=not_expired,
        expires_at=oauth.expires_at,
        scope=oauth.scope,
    )


@router.delete("/{client_key}/oauth", response_model=dict)
async def oauth_revoke(
    client_key: str,
    request: Request,
) -> dict:
    """Clear OAuth tokens for an MCP client (logout / re-auth prep)."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(
            status_code=404,
            detail=f"MCP client '{client_key}' not found",
        )

    agent.config.mcp.clients[client_key].oauth = None
    save_agent_config(agent.agent_id, agent.config)
    schedule_agent_reload(request, agent.agent_id)

    return {"message": "OAuth tokens cleared"}
