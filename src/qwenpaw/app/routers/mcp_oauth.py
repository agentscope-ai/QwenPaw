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
from datetime import UTC, datetime, timedelta
from typing import Dict, Optional, Tuple
from uuid import UUID
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..driver_config_service import DriverConfigService
from ...drivers.adapters.mcp_console import (
    attach_mcp_oauth_credential,
    detach_mcp_oauth_credential,
    mcp_oauth_credential_ref,
)
from ...drivers.constants import CREDENTIAL_KIND_OAUTH_AUTH_CODE, PROTOCOL_MCP
from ...drivers.credentials.store import AsyncCredentialStore
from ...drivers.credentials.types import CredentialRecord
from ...drivers.errors import CredentialNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp-oauth"])


def _mcp_card_path(workspace, client_key: str):
    return DriverConfigService(workspace).card_path(
        client_key,
        protocol=PROTOCOL_MCP,
    )


# ---------------------------------------------------------------------------
# In-memory state store: state_token -> OAuthSession (TTL 10 min)
# ---------------------------------------------------------------------------

_TTL_SECONDS = 600
_MAX_COMPLETIONS = 1024


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
        *,
        initiated_by: UUID | None = None,
        driver_id: UUID | None = None,
        driver_revision: int | None = None,
        postgres: bool = False,
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
        self.initiated_by = initiated_by
        self.driver_id = driver_id
        self.driver_revision = driver_revision
        self.postgres = postgres
        self.created_at = time.monotonic()

    def is_expired(self) -> bool:
        """Return True if this session has exceeded the TTL."""
        return (time.monotonic() - self.created_at) > _TTL_SECONDS


_state_store: Dict[str, OAuthSession] = {}
_completion_store: Dict[str, tuple[OAuthSession, str, float]] = {}


def _purge_expired() -> None:
    """Expire pending sessions and bound the short-lived completion cache."""
    now = time.monotonic()
    stale_completions = [
        key
        for key, (_, _, completed_at) in _completion_store.items()
        if now - completed_at > _TTL_SECONDS
    ]
    for key in stale_completions:
        _completion_store.pop(key, None)
    expired = [k for k, v in _state_store.items() if v.is_expired()]
    for k in expired:
        session = _state_store.pop(k)
        _completion_store[k] = (session, "expired", now)
    overflow = len(_completion_store) - _MAX_COMPLETIONS
    if overflow > 0:
        oldest = sorted(
            _completion_store,
            key=lambda key: _completion_store[key][2],
        )[:overflow]
        for key in oldest:
            _completion_store.pop(key, None)


def _record_completion(
    state: str,
    session: OAuthSession,
    status: str,
) -> None:
    _completion_store[state] = (session, status, time.monotonic())
    _purge_expired()


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
    except Exception as exc:
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
    except Exception as exc:
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
        if prm and prm.get("authorization_servers"):
            return prm["authorization_servers"][0]

    # Fall back to well-known PRM paths
    parsed = urlparse(mcp_url.rstrip("/"))
    root = f"{parsed.scheme}://{parsed.netloc}"
    path_suffix = parsed.path.lstrip("/")
    candidates = [
        (
            f"{root}/.well-known/oauth-protected-resource/{path_suffix}"
            if path_suffix
            else None
        ),
        f"{root}/.well-known/oauth-protected-resource",
    ]
    for url in candidates:
        if not url:
            continue
        prm = await _fetch_json(client, url)
        if prm and prm.get("authorization_servers"):
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
    except Exception as exc:
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
    expected_revision: Optional[int] = None


class OAuthStartResponse(BaseModel):
    """Response returned when an OAuth flow has been initiated."""

    auth_url: str
    session_id: str


class OAuthStatusResponse(BaseModel):
    """Current OAuth token status for an MCP client."""

    authorized: bool
    expires_at: float
    scope: str
    session_id: Optional[str] = None
    status: Optional[str] = None


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
    except Exception:
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

    Communicates only with the same-origin opener and never stores tokens or
    authorization results in browser storage.
    """
    data: dict = {"type": f"mcp-oauth-{status}"}
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
      if (window.opener && !window.opener.closed) {{
        try {{ window.opener.postMessage(data, window.location.origin); }}
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


@router.post(
    "/oauth/start/{client_key:path}",
    response_model=OAuthStartResponse,
)
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
    from ...access.dependencies import get_actor
    from ..agent_context import get_agent_for_request

    _purge_expired()

    # -- Validate agent exists and is enabled -----------------------------
    agent = await get_agent_for_request(request)
    agent_id = agent.agent_id
    actor = get_actor(request)
    initiated_by = actor.user_id
    pg_target = None
    postgres = False
    from ...identity.runtime import get_identity_schema
    from ..mcp.postgres_repository import (
        PostgresMCPRepository,
        is_postgres_mcp_enabled,
        workspace_uses_postgres,
    )

    if is_postgres_mcp_enabled():
        pg_repo = PostgresMCPRepository(schema=get_identity_schema())
        if await workspace_uses_postgres(agent, repository=pg_repo):
            async with pg_repo.transaction() as db:
                pg_target = await pg_repo.get_oauth_target(
                    session=db,
                    agent_key=agent_id,
                    client_key=client_key,
                )
            if pg_target is None:
                raise HTTPException(status_code=404, detail="mcp_not_found")
            if actor.user_id is None or not pg_target.enabled:
                raise HTTPException(status_code=403, detail="forbidden")
            if body.expected_revision is None:
                raise HTTPException(409, detail="expected_revision_required")
            if body.expected_revision != pg_target.revision:
                raise HTTPException(409, detail="mcp_revision_conflict")
            if pg_target.oauth_authorization_conflict:
                raise HTTPException(
                    status_code=400,
                    detail="Remove the existing Authorization header before starting OAuth.",
                )
            initiated_by = actor.user_id
            postgres = True
            endpoint_url = pg_target.endpoint_url
        else:
            card = await _load_mcp_card_for_oauth(agent, client_key)
            endpoint_url = str(card.endpoint.get("url") or body.url or "")
    else:
        card = await _load_mcp_card_for_oauth(agent, client_key)
        endpoint_url = str(card.endpoint.get("url") or body.url or "")
    if not endpoint_url:
        raise HTTPException(
            status_code=400,
            detail="OAuth MCP client must have a remote URL.",
        )

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
        ) = await _discover_oauth_metadata(endpoint_url)

    # -- Resolve client_id -------------------------------------------------
    existing_oauth = (
        None
        if postgres
        else await _load_optional_oauth_credential(agent, client_key)
    )
    client_id = body.client_id or (
        str(existing_oauth.public.get("client_id") or "")
        if existing_oauth
        else ""
    )
    if not client_id and registration_endpoint:
        client_id = (
            await _dynamic_register(registration_endpoint, redirect_uri) or ""
        )

    # -- PKCE --------------------------------------------------------------
    verifier = _generate_code_verifier()
    challenge = _code_challenge(verifier)
    state = secrets.token_hex(16)

    driver_id = None
    driver_revision = None
    if postgres:
        from ..mcp.oauth_repository import PostgresOAuthRepository

        assert pg_target is not None and initiated_by is not None
        driver_id = pg_target.driver_id
        driver_revision = pg_target.revision
        pg_repo = PostgresMCPRepository(schema=get_identity_schema())
        async with pg_repo.transaction() as db:
            current_target = await pg_repo.get_oauth_target(
                session=db,
                agent_key=agent_id,
                client_key=client_key,
            )
            if current_target != pg_target:
                raise HTTPException(status_code=409, detail="mcp_revision_conflict")
            await PostgresOAuthRepository(schema=get_identity_schema()).create(
                session=db,
                state=state,
                driver_id=driver_id,
                initiated_by=initiated_by,
                expires_at=datetime.now(UTC) + timedelta(seconds=_TTL_SECONDS),
            )

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
        initiated_by=initiated_by,
        driver_id=driver_id,
        driver_revision=driver_revision,
        postgres=postgres,
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


def _make_error_page(
    message: str,
    *,
    session: OAuthSession | None = None,
    session_id: str = "",
) -> HTMLResponse:
    """Return an HTML error page for the OAuth popup."""
    safe = _html_lib.escape(message)
    body = (
        "<p style='color:#c0392b;font-size:1.1em'>"
        "<strong>Authorization failed</strong></p>"
        f"<p style='color:#666;font-size:13px'>{safe}</p>"
    )
    extra_data = None
    if session is not None:
        extra_data = {
            "session_id": session_id,
            "client_key": session.client_key,
            "agent_id": session.agent_id,
            "error": "oauth_failed",
        }
    return HTMLResponse(
        _popup_html("error", body, extra_data=extra_data),
        status_code=400,
    )


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
    except Exception as exc:
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
    """Persist OAuth tokens into AsyncCredentialStore and update DriverCard.

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
    card = await _load_mcp_card_for_oauth_value_error(
        workspace,
        session.client_key,
    )
    config_service = DriverConfigService(workspace)
    store = config_service.credential_store
    oauth_ref = mcp_oauth_credential_ref(session.client_key)
    existing = await _load_optional_credential(store, oauth_ref)
    public = dict(existing.public) if existing else {}
    secrets_map = dict(existing.secrets) if existing else {}
    public.update(
        {
            "client_id": session.client_id
            or str(public.get("client_id") or ""),
            "scope": scope,
            "expires_at": expires_at,
            "token_endpoint": session.token_endpoint,
            "auth_endpoint": session.auth_endpoint
            or str(public.get("auth_endpoint") or ""),
        },
    )
    secrets_map["access_token"] = access_token
    if refresh_token:
        secrets_map["refresh_token"] = refresh_token

    await store.put(
        CredentialRecord(
            ref=oauth_ref,
            kind="oauth2_auth_code",
            public=public,
            secrets=secrets_map,
            meta={
                **(existing.meta if existing else {}),
                "updated_at": time.time(),
            },
        ),
    )
    card = attach_mcp_oauth_credential(card, oauth_ref)
    await config_service.save_card(card)


async def _persist_postgres_tokens(
    request: Request,
    session: OAuthSession,
    state: str,
    tokens: dict,
) -> None:
    """Atomically consume state, revalidate ownership, and bind new tokens."""
    if session.driver_id is None or session.initiated_by is None:
        raise ValueError("oauth_session_invalid")
    access_token = str(tokens.get("access_token") or "")
    if not access_token:
        raise ValueError("oauth_token_invalid")
    refresh_token = str(tokens.get("refresh_token") or "")
    try:
        expires_in = max(0, int(tokens.get("expires_in", 3600)))
    except (TypeError, ValueError) as exc:
        raise ValueError("oauth_token_invalid") from exc
    expires_at = time.time() + expires_in

    from ...identity.runtime import get_identity_schema
    from ..mcp.oauth_repository import PostgresOAuthRepository
    from ..mcp.postgres_repository import PostgresMCPRepository

    pg_repo = PostgresMCPRepository(schema=get_identity_schema())
    oauth_repo = PostgresOAuthRepository(schema=get_identity_schema())
    async with pg_repo.transaction() as db:
        await oauth_repo.consume(
            session=db,
            state=state,
            driver_id=session.driver_id,
            initiated_by=session.initiated_by,
        )
        target = await pg_repo.get_oauth_target(
            session=db,
            agent_key=session.agent_id,
            client_key=session.client_key,
        )
        if not _oauth_target_is_unchanged(session, target):
            raise ValueError("oauth_target_changed")
        secret_values = {"access_token": access_token}
        if refresh_token:
            secret_values["refresh_token"] = refresh_token
        await pg_repo.replace_bound_credential(
            session=db,
            target=target,
            actor_user_id=session.initiated_by,
            purpose="oauth",
            kind=CREDENTIAL_KIND_OAUTH_AUTH_CODE,
            public={
                "client_id": session.client_id,
                "scope": str(tokens.get("scope") or session.scope),
                "expires_at": expires_at,
                "token_endpoint": session.token_endpoint,
                "auth_endpoint": session.auth_endpoint,
            },
            secrets=secret_values,
        )
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is not None:
        workspace = await manager.get_agent(session.agent_id)
        await _reload_driver_best_effort(workspace, session.client_key)


def _oauth_target_is_unchanged(session: OAuthSession, target) -> bool:
    return bool(
        target is not None
        and target.enabled
        and target.driver_id == session.driver_id
        and target.revision == session.driver_revision
    )


async def _fail_postgres_session(session: OAuthSession, state: str) -> None:
    if (
        not session.postgres
        or session.driver_id is None
        or session.initiated_by is None
    ):
        return
    from ...identity.runtime import get_identity_schema
    from ..mcp.oauth_repository import PostgresOAuthRepository
    from ..mcp.postgres_repository import PostgresMCPRepository

    pg_repo = PostgresMCPRepository(schema=get_identity_schema())
    async with pg_repo.transaction() as db:
        await PostgresOAuthRepository(schema=get_identity_schema()).fail(
            session=db,
            state=state,
            driver_id=session.driver_id,
            initiated_by=session.initiated_by,
        )


def _workspace_credential_store(workspace) -> AsyncCredentialStore:
    return DriverConfigService(workspace).credential_store


async def _load_mcp_card_for_oauth(workspace, client_key: str):
    try:
        return await DriverConfigService(workspace).load_card(
            client_key,
            protocol=PROTOCOL_MCP,
        )
    except HTTPException as exc:
        raise HTTPException(
            status_code=404,
            detail=f"MCP client '{client_key}' not found",
        ) from exc


async def _load_mcp_card_for_oauth_value_error(workspace, client_key: str):
    try:
        return await _load_mcp_card_for_oauth(workspace, client_key)
    except HTTPException as exc:
        raise ValueError(
            f"MCP client '{client_key}' not found. "
            "Please create the client first, then re-authorize.",
        ) from exc


async def _load_optional_credential(
    store: AsyncCredentialStore,
    ref: str,
) -> CredentialRecord | None:
    try:
        return await store.get(ref)
    except CredentialNotFoundError:
        return None


async def _load_optional_oauth_credential(
    workspace,
    client_key: str,
) -> CredentialRecord | None:
    return await _load_optional_credential(
        _workspace_credential_store(workspace),
        mcp_oauth_credential_ref(client_key),
    )


async def _reload_driver_best_effort(workspace, client_key: str) -> None:
    await DriverConfigService(workspace).reload_driver_best_effort(client_key)


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
    MCP client's OAuth credential record, then returns HTML that
    notifies the opener popup window and closes itself.
    """
    if error or not code or not state:
        if state and (failed_session := _state_store.pop(state, None)) is not None:
            try:
                await _fail_postgres_session(failed_session, state)
            except Exception:
                logger.warning("MCP OAuth failure state could not be finalized")
            _record_completion(state, failed_session, "failed")
            return _make_error_page(
                "OAuth authorization was cancelled.",
                session=failed_session,
                session_id=state,
            )
        return _make_error_page("Missing 'code' or 'state' parameter.")

    session = _state_store.get(state)
    if session is None or session.is_expired():
        if session is not None:
            _state_store.pop(state, None)
            try:
                await _fail_postgres_session(session, state)
            except Exception:
                logger.warning("MCP OAuth expiry state could not be finalized")
            _record_completion(state, session, "expired")
        return _make_error_page(
            "OAuth session expired or not found. Please try again.",
            session=session,
            session_id=state,
        )

    try:
        # Remove the verifier before I/O so concurrent callbacks cannot reuse it.
        _state_store.pop(state, None)
        tokens = await _exchange_code_for_tokens(session, code)
        if session.postgres:
            await _persist_postgres_tokens(request, session, state, tokens)
        else:
            await _persist_tokens(request, session, tokens)
    except Exception:
        _state_store.pop(state, None)
        try:
            await _fail_postgres_session(session, state)
        except Exception:
            logger.warning("MCP OAuth failure state could not be finalized")
        _record_completion(state, session, "failed")
        logger.warning(
            "MCP OAuth callback rejected",
        )
        return _make_error_page(
            "OAuth authorization could not be completed.",
            session=session,
            session_id=state,
        )

    _record_completion(state, session, "completed")
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
                "session_id": state,
                "client_key": session.client_key,
                "agent_id": session.agent_id,
            },
        ),
    )


def _legacy_session_status(
    session_id: str | None,
    agent_id: str,
    client_key: str,
    initiated_by: UUID | None,
) -> str | None:
    if not session_id:
        return None
    pending = _state_store.get(session_id)
    if pending is not None:
        if (
            pending.agent_id != agent_id
            or pending.client_key != client_key
            or pending.initiated_by != initiated_by
        ):
            return None
        return "expired" if pending.is_expired() else "pending"
    completed = _completion_store.get(session_id)
    if completed is None:
        return None
    session, status, completed_at = completed
    if time.monotonic() - completed_at > _TTL_SECONDS:
        _completion_store.pop(session_id, None)
        return None
    if (
        session.agent_id != agent_id
        or session.client_key != client_key
        or session.initiated_by != initiated_by
    ):
        return None
    return status


@router.get(
    "/oauth/status/{client_key:path}",
    response_model=OAuthStatusResponse,
)
async def oauth_status(
    client_key: str,
    request: Request,
    session_id: Optional[str] = None,
) -> OAuthStatusResponse:
    """Return credential status, optionally correlated to one OAuth start."""
    from ...access.dependencies import get_actor
    from ...identity.runtime import get_identity_schema
    from ..agent_context import get_agent_for_request
    from ..mcp.postgres_repository import (
        PostgresMCPRepository,
        is_postgres_mcp_enabled,
        workspace_uses_postgres,
    )

    agent = await get_agent_for_request(request)
    actor = get_actor(request)
    if is_postgres_mcp_enabled():
        pg_repo = PostgresMCPRepository(schema=get_identity_schema())
        if await workspace_uses_postgres(agent, repository=pg_repo):
            if actor.user_id is None:
                raise HTTPException(status_code=403, detail="forbidden")
            from ..mcp.oauth_repository import PostgresOAuthRepository

            async with pg_repo.transaction() as db:
                target = await pg_repo.get_oauth_target(
                    session=db,
                    agent_key=agent.agent_id,
                    client_key=client_key,
                )
                if target is None:
                    raise HTTPException(status_code=404, detail="mcp_not_found")
                correlated = None
                if session_id:
                    correlated = await PostgresOAuthRepository(
                        schema=get_identity_schema()
                    ).status(
                        session=db,
                        state=session_id,
                        driver_id=target.driver_id,
                        initiated_by=actor.user_id,
                    )
            if session_id and correlated is None:
                raise HTTPException(404, detail="oauth_session_not_found")
            status = await pg_repo.bound_credential_status(
                agent_key=agent.agent_id,
                client_key=client_key,
                purpose="oauth",
            )
            not_expired = (
                status.expires_at <= 0 or status.expires_at > time.time()
            )
            correlation_status = correlated.status if correlated else None
            return OAuthStatusResponse(
                authorized=(
                    status.authorized
                    and not_expired
                    and (not session_id or correlation_status == "completed")
                ),
                expires_at=status.expires_at,
                scope=status.scope,
                session_id=session_id,
                status=correlation_status,
            )
    await _load_mcp_card_for_oauth(agent, client_key)
    correlation_status = _legacy_session_status(
        session_id,
        agent.agent_id,
        client_key,
        actor.user_id,
    )
    if session_id and correlation_status is None:
        raise HTTPException(404, detail="oauth_session_not_found")
    oauth = await _load_optional_oauth_credential(agent, client_key)
    if oauth is None or not oauth.secrets.get("access_token"):
        return OAuthStatusResponse(
            authorized=False,
            expires_at=0.0,
            scope="",
            session_id=session_id,
            status=correlation_status,
        )

    # Token is valid only when not expired (expires_at=0 means no expiry set)
    expires_at = float(oauth.public.get("expires_at") or 0.0)
    not_expired = expires_at <= 0 or expires_at > time.time()
    return OAuthStatusResponse(
        authorized=(
            not_expired
            and (not session_id or correlation_status == "completed")
        ),
        expires_at=expires_at,
        scope=str(oauth.public.get("scope") or ""),
        session_id=session_id,
        status=correlation_status,
    )


@router.delete("/oauth/{client_key:path}", response_model=dict)
async def oauth_revoke(
    client_key: str,
    request: Request,
    expected_revision: Optional[int] = None,
) -> dict:
    """Clear OAuth tokens for an MCP client (logout / re-auth prep)."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    from ...access.dependencies import get_actor
    from ...identity.runtime import get_identity_schema
    from ..mcp.postgres_repository import (
        PostgresMCPRepository,
        is_postgres_mcp_enabled,
        workspace_uses_postgres,
    )

    if is_postgres_mcp_enabled():
        pg_repo = PostgresMCPRepository(schema=get_identity_schema())
        if await workspace_uses_postgres(agent, repository=pg_repo):
            actor = get_actor(request)
            if actor.user_id is None:
                raise HTTPException(status_code=403, detail="forbidden")
            if expected_revision is None:
                raise HTTPException(409, detail="expected_revision_required")
            async with pg_repo.transaction() as db:
                target = await pg_repo.get_oauth_target(
                    session=db,
                    agent_key=agent.agent_id,
                    client_key=client_key,
                )
                if target is None:
                    raise HTTPException(status_code=404, detail="mcp_not_found")
                if target.revision != expected_revision:
                    raise HTTPException(409, detail="mcp_revision_conflict")
                await pg_repo.revoke_bound_credential(
                    session=db,
                    target=target,
                    actor_user_id=actor.user_id,
                    purpose="oauth",
                )
            await _reload_driver_best_effort(agent, client_key)
            return {"message": "OAuth tokens cleared"}
    card = await _load_mcp_card_for_oauth(agent, client_key)
    config_service = DriverConfigService(agent)
    store = config_service.credential_store
    await store.delete(mcp_oauth_credential_ref(client_key))
    card = detach_mcp_oauth_credential(card)
    await config_service.save_card(card)

    return {"message": "OAuth tokens cleared"}
