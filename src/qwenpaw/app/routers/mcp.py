# -*- coding: utf-8 -*-
"""API routes for MCP (Model Context Protocol) clients management."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Body, HTTPException, Path, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..mcp import oauth as mcp_oauth
from ..utils import schedule_agent_reload
from ...config.config import MCPClientAuth, MCPClientConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# Top-level (non-agent-scoped) router for the OAuth callback endpoint.  The
# callback URL is the redirect_uri registered with the AS; it cannot carry
# the agent_id (browser-driven 302 from external AS). agent_id is recovered
# from the pending OAuth session keyed by ``state``.
oauth_callback_router = APIRouter(tags=["mcp"])

# Placeholder redirect_uri used in 'paste' mode.
# The URL does not need to resolve; the user copies it from the browser's
# address bar after the AS redirect fails to connect.  The exact value must
# still match what was registered via DCR.
PASTE_REDIRECT_URI = "http://localhost:10112/oauth/callback"

# Timeout (seconds) for OAuth discovery / DCR / token network calls.
AUTH_PROBE_TIMEOUT = 10.0


class MCPClientInfo(BaseModel):
    """MCP client information for API responses."""

    key: str = Field(..., description="Unique client key identifier")
    name: str = Field(..., description="Client display name")
    description: str = Field(default="", description="Client description")
    enabled: bool = Field(..., description="Whether the client is enabled")
    transport: Literal["stdio", "streamable_http", "sse"] = Field(
        ...,
        description="MCP transport type",
    )
    url: str = Field(
        default="",
        description="Remote MCP endpoint URL (for HTTP/SSE transports)",
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers for remote transport",
    )
    command: str = Field(
        default="",
        description="Command to launch the MCP server",
    )
    args: List[str] = Field(
        default_factory=list,
        description="Command-line arguments",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables",
    )
    cwd: str = Field(
        default="",
        description="Working directory for stdio MCP command",
    )
    auth_state: Literal[
        "none",
        "oauth_pending",
        "oauth_active",
        "oauth_expired",
    ] = Field(
        default="none",
        description="OAuth authentication state",
    )
    auth_scope: str = Field(
        default="",
        description="OAuth scopes granted (when auth_state=oauth_active)",
    )
    auth_token_expires_at: int = Field(
        default=0,
        description=(
            "Unix timestamp when the access_token expires; "
            "0 = unknown / not applicable"
        ),
    )
    connection_status: Literal[
        "connected",
        "connecting",
        "disconnected",
    ] = Field(
        default="disconnected",
        description="Runtime MCP client connection status",
    )


class MCPClientCreateRequest(BaseModel):
    """Request body for creating/updating an MCP client."""

    name: str = Field(..., description="Client display name")
    description: str = Field(default="", description="Client description")
    enabled: bool = Field(
        default=True,
        description="Whether to enable the client",
    )
    transport: Literal["stdio", "streamable_http", "sse"] = Field(
        default="stdio",
        description="MCP transport type",
    )
    url: str = Field(
        default="",
        description="Remote MCP endpoint URL (for HTTP/SSE transports)",
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers for remote transport",
    )
    command: str = Field(
        default="",
        description="Command to launch the MCP server",
    )
    args: List[str] = Field(
        default_factory=list,
        description="Command-line arguments",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables",
    )
    cwd: str = Field(
        default="",
        description="Working directory for stdio MCP command",
    )


class MCPClientUpdateRequest(BaseModel):
    """Request body for updating an MCP client (all fields optional)."""

    name: Optional[str] = Field(None, description="Client display name")
    description: Optional[str] = Field(None, description="Client description")
    enabled: Optional[bool] = Field(
        None,
        description="Whether to enable the client",
    )
    transport: Optional[Literal["stdio", "streamable_http", "sse"]] = Field(
        None,
        description="MCP transport type",
    )
    url: Optional[str] = Field(
        None,
        description="Remote MCP endpoint URL (for HTTP/SSE transports)",
    )
    headers: Optional[Dict[str, str]] = Field(
        None,
        description="HTTP headers for remote transport",
    )
    command: Optional[str] = Field(
        None,
        description="Command to launch the MCP server",
    )
    args: Optional[List[str]] = Field(
        None,
        description="Command-line arguments",
    )
    env: Optional[Dict[str, str]] = Field(
        None,
        description="Environment variables",
    )
    cwd: Optional[str] = Field(
        None,
        description="Working directory for stdio MCP command",
    )


def _restore_original_values(
    incoming: Dict[str, str],
    existing: Dict[str, str],
) -> Dict[str, str]:
    """Preserve original values when incoming matches their masked form."""
    restored: Dict[str, str] = {}
    for k, v in incoming.items():
        if k in existing and v == _mask_env_value(existing[k]):
            restored[k] = existing[k]
        else:
            restored[k] = v
    return restored


def _mask_env_value(value: str) -> str:
    """
    Mask environment variable value showing first 2-3 chars and last 4 chars.

    Examples:
        sk-proj-1234567890abcdefghij1234 -> sk-****************************1234
        abc123456789xyz -> ab***********xyz (if no dash)
        my-api-key-value -> my-************lue
        short123 -> ******** (8 chars or less, fully masked)
    """
    if not value:
        return value

    length = len(value)
    if length <= 8:
        # For short values, just mask everything
        return "*" * length

    # Show first 2-3 characters (3 if there's a dash at position 2)
    prefix_len = 3 if length > 2 and value[2] == "-" else 2
    prefix = value[:prefix_len]

    # Show last 4 characters
    suffix = value[-4:]

    # Calculate masked section length (at least 4 asterisks)
    masked_len = max(length - prefix_len - 4, 4)

    return f"{prefix}{'*' * masked_len}{suffix}"


def _build_client_info(
    key: str,
    client: MCPClientConfig,
    mcp_manager: Any = None,
) -> MCPClientInfo:
    """Build MCPClientInfo from config with masked env values.

    When ``mcp_manager`` is provided, ``connection_status`` reflects the
    runtime state of the live MCP client; otherwise it is inferred purely
    from ``client.enabled``.
    """
    masked_env = (
        {k: _mask_env_value(v) for k, v in client.env.items()}
        if client.env
        else {}
    )
    masked_headers = (
        {k: _mask_env_value(v) for k, v in client.headers.items()}
        if client.headers
        else {}
    )

    auth_state = "none"
    auth_scope = ""
    auth_token_expires_at = 0
    if client.auth is not None and client.auth.type == "oauth2":
        if client.auth.access_token or client.auth.refresh_token:
            auth_state = "oauth_active"
            auth_scope = client.auth.scope
            auth_token_expires_at = client.auth.token_expires_at
        else:
            # DCR completed but tokens not yet obtained (mid-flow)
            auth_state = "oauth_pending"

    connection_status: Literal[
        "connected",
        "connecting",
        "disconnected",
    ] = "disconnected"
    if client.enabled and mcp_manager is not None:
        clients = mcp_manager._clients  # pylint: disable=protected-access
        live_client = clients.get(key)
        if live_client is None:
            connection_status = "disconnected"
        elif getattr(live_client, "is_connected", False):
            connection_status = "connected"
        else:
            connection_status = "connecting"

    return MCPClientInfo(
        key=key,
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=client.transport,
        url=client.url,
        headers=masked_headers,
        command=client.command,
        args=client.args,
        env=masked_env,
        cwd=client.cwd,
        auth_state=auth_state,
        auth_scope=auth_scope,
        auth_token_expires_at=auth_token_expires_at,
        connection_status=connection_status,
    )


class MCPToolInfo(BaseModel):
    """MCP tool information returned from a connected server."""

    name: str = Field(..., description="Tool name")
    description: str = Field(default="", description="Tool description")
    input_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for the tool's input parameters",
    )


@router.get(
    "/{client_key}/tools",
    response_model=List[MCPToolInfo],
    summary="List tools from a connected MCP server",
)
async def list_mcp_tools(
    request: Request,
    client_key: str = Path(...),
) -> List[MCPToolInfo]:
    """Query a running MCP server for its available tools.

    Returns 503 if the client is not yet connected, empty list if
    disabled, or 502 if the MCP server query fails.
    """
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)

    mcp_config = agent.config.mcp
    if mcp_config is None or client_key not in (mcp_config.clients or {}):
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_config = mcp_config.clients[client_key]
    if not client_config.enabled:
        return []

    mcp_manager = agent.mcp_manager
    if mcp_manager is None:
        raise HTTPException(
            503,
            detail="MCP manager is not ready yet, please try again later",
        )

    client = await mcp_manager.get_client(client_key)
    if client is None or not getattr(client, "is_connected", False):
        raise HTTPException(
            503,
            detail="MCP server is still connecting, please try again later",
        )

    try:
        tools = await client.list_tools()
    except Exception as e:
        logger.warning(
            f"Failed to list tools for MCP client '{client_key}': {e}",
        )
        raise HTTPException(
            502,
            detail=f"Failed to query tools from MCP server: {e}",
        ) from e

    return [
        MCPToolInfo(
            name=t.name,
            description=getattr(t, "description", "") or "",
            input_schema=getattr(t, "inputSchema", {}) or {},
        )
        for t in tools
    ]


@router.get(
    "",
    response_model=List[MCPClientInfo],
    summary="List all MCP clients",
)
async def list_mcp_clients(request: Request) -> List[MCPClientInfo]:
    """Get list of all configured MCP clients."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    mcp_config = agent.config.mcp
    if mcp_config is None or not mcp_config.clients:
        return []

    mcp_manager = getattr(agent, "mcp_manager", None)
    return [
        _build_client_info(key, client, mcp_manager)
        for key, client in mcp_config.clients.items()
    ]


@router.get(
    "/{client_key}",
    response_model=MCPClientInfo,
    summary="Get MCP client details",
)
async def get_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Get details of a specific MCP client."""
    from ..agent_context import get_agent_for_request

    agent = await get_agent_for_request(request)
    mcp_config = agent.config.mcp
    if mcp_config is None:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client = mcp_config.clients.get(client_key)
    if client is None:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")
    return _build_client_info(
        client_key,
        client,
        getattr(agent, "mcp_manager", None),
    )


@router.post(
    "",
    response_model=MCPClientInfo,
    summary="Create a new MCP client",
    status_code=201,
)
async def create_mcp_client(
    request: Request,
    client_key: str = Body(..., embed=True),
    client: MCPClientCreateRequest = Body(..., embed=True),
) -> MCPClientInfo:
    """Create a new MCP client configuration."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config, MCPConfig

    agent = await get_agent_for_request(request)

    # Initialize mcp config if not exists
    if agent.config.mcp is None:
        agent.config.mcp = MCPConfig(clients={})

    # Check if client already exists
    if client_key in agent.config.mcp.clients:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' already exists. Use PUT to "
            f"update.",
        )

    # Create new client config
    new_client = MCPClientConfig(
        name=client.name,
        description=client.description,
        enabled=client.enabled,
        transport=client.transport,
        url=client.url,
        headers=client.headers,
        command=client.command,
        args=client.args,
        env=client.env,
        cwd=client.cwd,
    )

    # Add to agent's config and save
    agent.config.mcp.clients[client_key] = new_client
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return _build_client_info(
        client_key,
        new_client,
        getattr(agent, "mcp_manager", None),
    )


@router.put(
    "/{client_key}",
    response_model=MCPClientInfo,
    summary="Update an MCP client",
)
async def update_mcp_client(
    request: Request,
    client_key: str = Path(...),
    updates: MCPClientUpdateRequest = Body(...),
) -> MCPClientInfo:
    """Update an existing MCP client configuration."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    existing = agent.config.mcp.clients[client_key]

    # Update fields if provided
    update_data = updates.model_dump(exclude_unset=True)

    # Restore masked env/header values to originals before replacing
    if "env" in update_data and update_data["env"] is not None:
        update_data["env"] = _restore_original_values(
            update_data["env"],
            existing.env or {},
        )

    if "headers" in update_data and update_data["headers"] is not None:
        update_data["headers"] = _restore_original_values(
            update_data["headers"],
            existing.headers or {},
        )

    merged_data = existing.model_dump(mode="json")
    merged_data.update(update_data)
    updated_client = MCPClientConfig.model_validate(merged_data)
    agent.config.mcp.clients[client_key] = updated_client

    # Save updated config
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return _build_client_info(
        client_key,
        updated_client,
        getattr(agent, "mcp_manager", None),
    )


@router.patch(
    "/{client_key}/toggle",
    response_model=MCPClientInfo,
    summary="Toggle MCP client enabled status",
)
async def toggle_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> MCPClientInfo:
    """Toggle the enabled status of an MCP client."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client = agent.config.mcp.clients[client_key]

    # Toggle enabled status
    client.enabled = not client.enabled
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return _build_client_info(
        client_key,
        client,
        getattr(agent, "mcp_manager", None),
    )


@router.delete(
    "/{client_key}",
    response_model=Dict[str, str],
    summary="Delete an MCP client",
)
async def delete_mcp_client(
    request: Request,
    client_key: str = Path(...),
) -> Dict[str, str]:
    """Delete an MCP client configuration."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    # Remove client
    del agent.config.mcp.clients[client_key]
    save_agent_config(agent.agent_id, agent.config)

    # Hot reload config (async, non-blocking)
    schedule_agent_reload(request, agent.agent_id)

    return {"message": f"MCP client '{client_key}' deleted successfully"}


# ---------------------------------------------------------------------------
# OAuth 2.1 flow for HTTP MCP clients
# ---------------------------------------------------------------------------


class OAuthBeginResponse(BaseModel):
    """Response payload for ``POST /mcp/{key}/auth/oauth/begin``."""

    authorize_url: str = Field(..., description="URL to open in browser")
    state: str = Field(..., description="OAuth state used for this flow")
    mode: Literal["auto", "paste"] = Field(
        ...,
        description=(
            "Which redirect handling to expect; the UI uses this to render "
            "the appropriate instructions"
        ),
    )
    redirect_uri: str = Field(
        ...,
        description="Redirect URI registered with the authorization server",
    )


def _detect_oauth_mode(
    request: Request,
    browser_origin: str = "",
) -> Literal["auto", "paste"]:
    """Decide whether the OAuth callback can hit QwenPaw directly.

    'auto' means we can register a real QwenPaw URL as the redirect_uri so
    the browser's 302 lands back on us. 'paste' means we use a placeholder
    redirect_uri and ask the user to manually paste the failed callback
    URL back into the UI.

    Resolution order:
    1. QWENPAW_OAUTH_MODE env var (force override)
    2. Configured public_url (settings.json > QWENPAW_PUBLIC_URL env) → auto
    3. browser_origin from frontend (always reachable from the browser) → auto
    4. startup params (--host / --port) → auto
    5. Request Host header heuristic (localhost → auto, else → paste)
    """
    forced = os.environ.get("QWENPAW_OAUTH_MODE", "").strip().lower()
    if forced in ("auto", "paste"):
        return forced  # type: ignore[return-value]

    from .settings import get_effective_public_url

    if get_effective_public_url():
        return "auto"

    if browser_origin:
        return "auto"

    from .settings import _derive_url_from_startup_params

    if _derive_url_from_startup_params():
        return "auto"

    host_header = request.headers.get("host", "").split(":")[0].lower()
    client_host = request.client.host if request.client else ""
    local = ("127.0.0.1", "localhost", "::1")
    if host_header in local or client_host in local:
        return "auto"

    return "paste"


def _derive_auto_redirect_uri(
    request: Request,
    browser_origin: str = "",
) -> str:
    """Compute the redirect_uri used in 'auto' mode.

    Resolution order:
    1. ``public_url`` from settings.json (user-configured via UI)
    2. ``QWENPAW_PUBLIC_URL`` environment variable
    3. ``browser_origin`` sent by the frontend (the address the user actually
       typed into their browser — most reliable for reachability)
    4. Derived from ``--host`` / ``--port`` startup parameters
    5. ``X-Forwarded-*`` headers (reverse proxy) / Request ``Host`` header
    """
    from .settings import get_effective_public_url

    public = get_effective_public_url()
    if public:
        return f"{public}/api/mcp/oauth/callback"

    if browser_origin:
        from .settings import _derive_url_from_startup_params
        from urllib.parse import urlparse as _urlparse

        parsed_bo = _urlparse(browser_origin)
        startup = _derive_url_from_startup_params()
        if startup:
            parsed_su = _urlparse(startup)
            bo_port = parsed_bo.port or (
                443 if parsed_bo.scheme == "https" else 80
            )
            su_port = parsed_su.port or 80
            if bo_port != su_port:
                # Dev mode: frontend port differs from backend port.
                # Use browser's hostname but backend's port so the callback
                # reaches the API server.
                host_part = parsed_bo.hostname or "127.0.0.1"
                base = f"{parsed_bo.scheme}://{host_part}:{su_port}"
                return f"{base}/api/mcp/oauth/callback"
        base = browser_origin.rstrip("/")
        return f"{base}/api/mcp/oauth/callback"

    from .settings import _derive_url_from_startup_params

    startup = _derive_url_from_startup_params()
    if startup:
        return f"{startup}/api/mcp/oauth/callback"

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host",
        "localhost",
    )
    return f"{proto}://{host}/api/mcp/oauth/callback"


def _all_candidate_redirect_uris(request: Request) -> List[str]:
    """All redirect_uris registered with the AS via DCR.

    We register both placeholders so the same DCR client_id can be reused
    regardless of which mode the user ends up in.
    """
    auto_uri = _derive_auto_redirect_uri(request)
    return list({auto_uri, PASTE_REDIRECT_URI})


async def _ensure_oauth_metadata_and_client(
    request: Request,
    client_key: str,
    client_cfg: MCPClientConfig,
) -> MCPClientAuth:
    """Discover AS metadata + perform DCR if needed; persist on the cfg.

    Idempotent: skips network work when ``client_cfg.auth`` already has
    all required fields.
    """
    import httpx

    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)

    auth = client_cfg.auth or MCPClientAuth()
    redirect_uris = _all_candidate_redirect_uris(request)

    need_discovery = not (auth.authorization_endpoint and auth.token_endpoint)
    need_registration = not auth.client_id

    if not (need_discovery or need_registration):
        return auth

    async with httpx.AsyncClient(timeout=AUTH_PROBE_TIMEOUT) as http:
        if need_discovery:
            if not client_cfg.url:
                raise HTTPException(
                    400,
                    detail=(
                        "MCP client has no URL configured; OAuth requires "
                        "an HTTP transport with a reachable URL"
                    ),
                )
            try:
                resource_md = await mcp_oauth.discover_resource_metadata(
                    client_cfg.url,
                    http=http,
                )
            except mcp_oauth.OAuthError as e:
                raise HTTPException(
                    400,
                    detail=f"resource metadata discovery failed: {e.message}",
                ) from e

            issuers = resource_md.get("authorization_servers") or []
            if not issuers:
                raise HTTPException(
                    400,
                    detail="resource metadata lists no authorization_servers",
                )
            issuer = issuers[0]

            try:
                as_md = await mcp_oauth.discover_authorization_server(
                    issuer,
                    http=http,
                )
            except mcp_oauth.OAuthError as e:
                raise HTTPException(
                    400,
                    detail=f"AS metadata discovery failed: {e.message}",
                ) from e

            auth.authorization_endpoint = as_md.get(
                "authorization_endpoint",
                "",
            )
            auth.token_endpoint = as_md.get("token_endpoint", "")
            auth.registration_endpoint = as_md.get(
                "registration_endpoint",
                "",
            )
            auth.revocation_endpoint = as_md.get("revocation_endpoint", "")
            auth.resource = resource_md.get("resource") or client_cfg.url

            if not auth.authorization_endpoint or not auth.token_endpoint:
                raise HTTPException(
                    400,
                    detail=(
                        "Authorization server metadata is missing required "
                        "endpoints"
                    ),
                )

        if need_registration:
            if not auth.registration_endpoint:
                raise HTTPException(
                    400,
                    detail=(
                        "Authorization server does not support Dynamic "
                        "Client Registration; manual client_id "
                        "configuration is not implemented yet"
                    ),
                )
            try:
                reg = await mcp_oauth.dynamic_client_register(
                    registration_endpoint=auth.registration_endpoint,
                    redirect_uris=redirect_uris,
                    http=http,
                )
            except mcp_oauth.OAuthError as e:
                raise HTTPException(
                    400,
                    detail=f"DCR failed: {e.message}",
                ) from e
            auth.client_id = reg.get("client_id", "")
            auth.client_secret = reg.get("client_secret", "")
            auth.client_secret_expires_at = int(
                reg.get("client_secret_expires_at") or 0,
            )

    client_cfg.auth = auth
    agent.config.mcp.clients[client_key] = client_cfg
    save_agent_config(agent.agent_id, agent.config)
    return auth


@router.post(
    "/{client_key}/auth/oauth/begin",
    response_model=OAuthBeginResponse,
    summary="Start an OAuth authorization flow for an MCP client",
)
async def oauth_begin(
    request: Request,
    client_key: str = Path(...),
    body: dict | None = Body(None),
) -> OAuthBeginResponse:
    """Discover AS metadata, perform DCR, return authorize URL."""
    from ..agent_context import get_agent_for_request

    browser_origin = ""
    if body and isinstance(body.get("browser_origin"), str):
        browser_origin = body["browser_origin"].strip().rstrip("/")

    agent = await get_agent_for_request(request)

    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_cfg = agent.config.mcp.clients[client_key]
    if client_cfg.transport not in ("streamable_http", "sse"):
        raise HTTPException(
            400,
            detail="OAuth is only supported for HTTP/SSE MCP transports",
        )

    auth = await _ensure_oauth_metadata_and_client(
        request,
        client_key,
        client_cfg,
    )

    mode = _detect_oauth_mode(request, browser_origin)
    redirect_uri = (
        _derive_auto_redirect_uri(request, browser_origin)
        if mode == "auto"
        else PASTE_REDIRECT_URI
    )

    verifier, challenge = mcp_oauth.make_pkce_pair()
    state = mcp_oauth.make_state()
    authorize_url = mcp_oauth.build_authorize_url(
        authorization_endpoint=auth.authorization_endpoint,
        client_id=auth.client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
        resource=auth.resource,
        scope=auth.scope,
    )

    await mcp_oauth.register_pending(
        state,
        mcp_oauth.PendingOAuth(
            agent_id=agent.agent_id,
            client_key=client_key,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            token_endpoint=auth.token_endpoint,
            client_id=auth.client_id,
            client_secret=auth.client_secret,
            resource=auth.resource,
            scope=auth.scope,
            mode=mode,
            expires_at=time.time() + mcp_oauth.PENDING_TTL_SECONDS,
        ),
    )

    return OAuthBeginResponse(
        authorize_url=authorize_url,
        state=state,
        mode=mode,
        redirect_uri=redirect_uri,
    )


class OAuthCompleteRequest(BaseModel):
    """Body for ``POST /mcp/{key}/auth/oauth/complete`` (paste mode)."""

    callback_url: str = Field(
        ...,
        description=(
            "Full URL the user copied from the browser address bar after "
            "the AS redirect failed to connect (paste mode)"
        ),
    )


class OAuthCompleteResponse(BaseModel):
    """Response payload for both auto- and paste-mode completion."""

    ok: bool
    client_key: str
    auth_state: Literal["oauth_active"]
    token_expires_at: int
    scope: str = ""


async def _complete_oauth_flow(
    request: Request,
    code: str,
    state: str,
    expected_client_key: Optional[str] = None,
) -> OAuthCompleteResponse:
    """Shared OAuth completion path used by both auto and paste modes.

    Looks up the pending session, exchanges the code, persists the tokens,
    and triggers a hot reload of the affected MCP client.
    """
    from ...config.config import load_agent_config, save_agent_config

    pending = await mcp_oauth.pop_pending(state)
    if pending is None:
        raise HTTPException(
            400,
            detail="OAuth session expired or unknown state",
        )

    if (
        expected_client_key is not None
        and pending.client_key != expected_client_key
    ):
        raise HTTPException(
            400,
            detail=(
                f"This OAuth callback belongs to MCP client "
                f"'{pending.client_key}', not '{expected_client_key}'."
            ),
        )

    try:
        tokens = await mcp_oauth.exchange_code(
            token_endpoint=pending.token_endpoint,
            code=code,
            code_verifier=pending.code_verifier,
            redirect_uri=pending.redirect_uri,
            client_id=pending.client_id,
            client_secret=pending.client_secret,
        )
    except mcp_oauth.OAuthError as e:
        raise HTTPException(
            400,
            detail=f"token exchange failed: {e.code}: {e.message}",
        ) from e

    cfg = load_agent_config(pending.agent_id)
    if cfg.mcp is None or pending.client_key not in cfg.mcp.clients:
        raise HTTPException(
            410,
            detail=("MCP client was deleted while OAuth flow was in progress"),
        )

    client_cfg = cfg.mcp.clients[pending.client_key]
    auth = client_cfg.auth or MCPClientAuth()
    auth.access_token = tokens.get("access_token", "")
    if "refresh_token" in tokens:
        auth.refresh_token = tokens["refresh_token"]
    auth.token_expires_at = mcp_oauth.compute_token_expires_at(
        tokens.get("expires_in"),
    )
    auth.scope = tokens.get("scope", auth.scope)
    client_cfg.auth = auth
    cfg.mcp.clients[pending.client_key] = client_cfg
    save_agent_config(pending.agent_id, cfg)

    # Trigger a hot reload of just this MCP client so the new bearer
    # token takes effect immediately without restarting the agent.
    try:
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is not None:
            agent = await manager.get_agent(pending.agent_id)
            if agent and agent.mcp_manager:
                await agent.mcp_manager.replace_client(
                    pending.client_key,
                    client_cfg,
                )
    except Exception as e:
        logger.warning(
            "Tokens persisted but MCP client reconnect failed for '%s': %s",
            pending.client_key,
            e,
        )

    return OAuthCompleteResponse(
        ok=True,
        client_key=pending.client_key,
        auth_state="oauth_active",
        token_expires_at=auth.token_expires_at,
        scope=auth.scope,
    )


@router.post(
    "/{client_key}/auth/oauth/complete",
    response_model=OAuthCompleteResponse,
    summary="Complete an OAuth flow by pasting the callback URL",
)
async def oauth_complete_paste(
    request: Request,  # pylint: disable=unused-argument
    client_key: str = Path(...),
    body: OAuthCompleteRequest = Body(...),
) -> OAuthCompleteResponse:
    """Paste-mode completion: parse callback URL and finish the OAuth flow."""
    params = mcp_oauth.parse_callback_url(body.callback_url)

    if params.get("error"):
        raise HTTPException(
            400,
            detail=(
                f"authorization server returned error: "
                f"{params['error']} - "
                f"{params.get('error_description', '')}"
            ),
        )

    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        raise HTTPException(
            400,
            detail=(
                "callback URL is missing 'code' or 'state' query parameter"
            ),
        )

    return await _complete_oauth_flow(
        request,
        code,
        state,
        expected_client_key=client_key,
    )


@router.delete(
    "/{client_key}/auth",
    response_model=Dict[str, str],
    summary="Sign out of an OAuth-authenticated MCP client",
)
async def oauth_signout(
    request: Request,
    client_key: str = Path(...),
    revoke_remote: bool = False,
) -> Dict[str, str]:
    """Clear stored OAuth state for a client; optionally revoke remotely."""
    from ..agent_context import get_agent_for_request
    from ...config.config import save_agent_config

    agent = await get_agent_for_request(request)
    if agent.config.mcp is None or client_key not in agent.config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_cfg = agent.config.mcp.clients[client_key]
    auth = client_cfg.auth
    if auth is None or auth.type != "oauth2":
        return {"message": "client was not OAuth-authenticated; nothing to do"}

    if revoke_remote and auth.revocation_endpoint and auth.refresh_token:
        await mcp_oauth.revoke_token(
            revocation_endpoint=auth.revocation_endpoint,
            token=auth.refresh_token,
            token_type_hint="refresh_token",
            client_id=auth.client_id,
            client_secret=auth.client_secret,
        )

    auth.access_token = ""
    auth.refresh_token = ""
    auth.token_expires_at = 0
    auth.scope = ""
    client_cfg.auth = auth
    agent.config.mcp.clients[client_key] = client_cfg
    save_agent_config(agent.agent_id, agent.config)

    schedule_agent_reload(request, agent.agent_id)

    return {"message": f"OAuth signed out for MCP client '{client_key}'"}


# ---------------------------------------------------------------------------
# OAuth callback (auto mode) — non-agent-scoped, public path
# ---------------------------------------------------------------------------


_CALLBACK_HTML_OK = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>QwenPaw OAuth</title>
<style>
body {{
  font-family: system-ui, sans-serif;
  padding: 48px; text-align: center;
}}
h1 {{ color: #16a34a; margin-bottom: 8px; }}
p {{ color: #475569; }}
.hint {{ margin-top: 16px; color: #94a3b8; font-size: 13px; }}
</style>
</head>
<body>
<h1>&#10003; Authentication complete</h1>
<p>MCP client <code>{client_key}</code> is now connected.</p>
<p class="hint" id="hint">
  This tab will close automatically&hellip;
</p>
<script>
(function () {{
  try {{
    if (window.opener && !window.opener.closed) {{
      window.opener.postMessage(
        {{ type: 'qwenpaw:mcp-oauth',
           status: 'success',
           clientKey: {client_key_json} }},
        '*'
      );
    }}
  }} catch (_) {{ /* ignore */ }}
  setTimeout(function () {{
    try {{ window.close(); }} catch (_) {{}}
    setTimeout(function () {{
      var h = document.getElementById('hint');
      if (h) h.textContent = 'You can close this tab now.';
    }}, 400);
  }}, 600);
}})();
</script>
</body>
</html>"""


_CALLBACK_HTML_ERR = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>QwenPaw OAuth</title>
<style>
body {{
  font-family: system-ui, sans-serif;
  padding: 48px; text-align: center;
}}
h1 {{ color: #dc2626; margin-bottom: 8px; }}
pre {{
  text-align: left; background: #f1f5f9;
  padding: 16px; display: inline-block;
}}
</style>
</head>
<body>
<h1>&#10005; Authentication failed</h1>
<pre>{detail}</pre>
<p>You can close this tab and try again from QwenPaw.</p>
</body>
</html>"""


@oauth_callback_router.get(
    "/mcp/oauth/callback",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="OAuth redirect target (auto mode)",
)
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> HTMLResponse:
    """OAuth redirect target invoked by the AS after user authorization."""
    if error:
        return HTMLResponse(
            _CALLBACK_HTML_ERR.format(
                detail=f"{error}: {error_description or ''}",
            ),
            status_code=400,
        )

    if not code or not state:
        return HTMLResponse(
            _CALLBACK_HTML_ERR.format(detail="missing code/state"),
            status_code=400,
        )

    try:
        result = await _complete_oauth_flow(request, code=code, state=state)
    except HTTPException as e:
        return HTMLResponse(
            _CALLBACK_HTML_ERR.format(detail=str(e.detail)),
            status_code=e.status_code,
        )
    except Exception as e:  # pragma: no cover - safety net
        logger.exception("Unexpected error in OAuth callback")
        return HTMLResponse(
            _CALLBACK_HTML_ERR.format(detail=f"unexpected error: {e}"),
            status_code=500,
        )

    return HTMLResponse(
        _CALLBACK_HTML_OK.format(
            client_key=result.client_key,
            client_key_json=json.dumps(result.client_key),
        ),
    )
