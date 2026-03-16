# -*- coding: utf-8 -*-
"""API routes for MCP OAuth authentication with auto-discovery.

Implements the MCP Authorization specification for HTTP transport.
Supports automatic metadata discovery and dynamic client registration.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ...config import load_config, save_config
from ...config.config import MCPOAuthDiscovery
from ..mcp.oauth import get_oauth_handler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])


class OAuthStartResponse(BaseModel):
    """Response for OAuth authorization start."""

    auth_url: str = Field(
        ...,
        description="URL to redirect user for authorization",
    )


class OAuthStatusResponse(BaseModel):
    """Response for OAuth status check."""

    authorized: bool = Field(..., description="Whether OAuth is authorized")
    requires_auth: bool = Field(
        False,
        description="Whether server requires OAuth (returned 401)",
    )
    expires_at: Optional[float] = Field(
        None,
        description="Token expiration timestamp",
    )


@router.post("/{client_key}/authorize", response_model=OAuthStartResponse)
async def start_oauth(client_key: str, request: Request) -> OAuthStartResponse:
    """Start OAuth authorization flow for an MCP client.

    This endpoint performs automatic OAuth discovery:
    1. Fetches metadata from /.well-known/oauth-authorization-server
    2. Registers client dynamically if needed
    3. Returns authorization URL for user to visit

    Args:
        client_key: MCP client identifier
        request: FastAPI request object for building callback URL

    Returns:
        OAuthStartResponse with auth_url
    """
    config = load_config()

    # Check if client exists
    if client_key not in config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_config = config.mcp.clients[client_key]

    # Only HTTP transports support OAuth
    if client_config.transport == "stdio":
        raise HTTPException(
            400,
            detail="OAuth is only supported for HTTP-based transports",
        )

    if not client_config.url:
        raise HTTPException(400, detail="MCP client URL is required for OAuth")

    handler = get_oauth_handler()
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/mcp/oauth/callback"

    # Check if we need to discover OAuth metadata
    if (
        not client_config.oauth_discovery
        or not client_config.oauth_discovery.client_id
    ):
        try:
            # Step 1: Discover OAuth metadata
            logger.info(f"Discovering OAuth metadata for '{client_key}'")
            metadata = await handler.discover_metadata(client_config.url)

            # Step 2: Dynamic Client Registration (if supported)
            if metadata.registration_endpoint:
                logger.info(f"Registering OAuth client for '{client_key}'")
                client_id, client_secret = await handler.register_client(
                    registration_endpoint=metadata.registration_endpoint,
                    redirect_uris=[redirect_uri],
                    client_name=f"CoPaw - {client_config.name}",
                )
            else:
                # Server doesn't support DCR, client_id must be pre-configured
                raise HTTPException(
                    400,
                    detail=(
                        "Server does not support Dynamic Client Registration. "
                        "Please configure client_id manually."
                    ),
                )

            # Store discovered OAuth configuration
            oauth_discovery = MCPOAuthDiscovery(
                authorization_endpoint=metadata.authorization_endpoint,
                token_endpoint=metadata.token_endpoint,
                registration_endpoint=metadata.registration_endpoint,
                client_id=client_id,
                client_secret=client_secret,
                scopes_supported=metadata.scopes_supported,
                # RFC 8707: use MCP server URL as resource
                resource=client_config.url,
            )

            config.mcp.clients[client_key].oauth_discovery = oauth_discovery
            save_config(config)

            logger.info(f"OAuth discovery completed for '{client_key}'")

        except HTTPException:
            # Re-raise HTTPException as-is (e.g., 400 for no DCR support)
            raise
        except Exception as e:
            logger.exception(f"OAuth discovery failed for '{client_key}'")
            raise HTTPException(
                500,
                detail=f"OAuth discovery failed: {e}",
            ) from e

    oauth_discovery = config.mcp.clients[client_key].oauth_discovery

    # Ensure resource is set (required by some MCP servers per RFC 8707)
    if oauth_discovery and not oauth_discovery.resource:
        oauth_discovery.resource = client_config.url
        config.mcp.clients[client_key].oauth_discovery = oauth_discovery
        save_config(config)

    # Generate authorization URL
    auth_url = handler.generate_auth_url(
        client_key=client_key,
        oauth_discovery=oauth_discovery,
        redirect_uri=redirect_uri,
    )

    logger.info(f"Started OAuth flow for MCP client '{client_key}'")
    return OAuthStartResponse(auth_url=auth_url)


@router.get("/callback")
async def oauth_callback(
    request: Request,  # pylint: disable=unused-argument
    state: str = Query(..., description="OAuth state parameter"),
    code: str = Query(..., description="Authorization code"),
    error: Optional[str] = Query(None, description="OAuth error"),
    error_description: Optional[str] = Query(
        None,
        description="Error description",
    ),
) -> HTMLResponse:
    """Handle OAuth callback from authorization server.

    Exchanges the authorization code for tokens and stores them.
    Returns an HTML page that closes the popup window.
    """
    # Handle OAuth errors
    if error:
        logger.warning(f"OAuth callback error: {error} - {error_description}")
        return _render_callback_page(
            success=False,
            message=error_description or error,
        )

    try:
        handler = get_oauth_handler()
        config = load_config()

        # Get client key from pending auth
        client_key = handler.get_pending_client_key(state)
        if not client_key:
            return _render_callback_page(
                success=False,
                message="Invalid or expired authorization state",
            )

        client_config = config.mcp.clients.get(client_key)
        if not client_config or not client_config.oauth_discovery:
            return _render_callback_page(
                success=False,
                message=f"Client '{client_key}' configuration not found",
            )

        # Exchange code for tokens
        client_key, oauth_token = await handler.handle_callback(
            state=state,
            code=code,
            oauth_discovery=client_config.oauth_discovery,
        )

        # Save token and clear requires_auth flag
        config.mcp.clients[client_key].oauth_token = oauth_token
        config.mcp.clients[client_key].requires_auth = False
        save_config(config)

        logger.info(f"OAuth authorization completed for client '{client_key}'")
        return _render_callback_page(
            success=True,
            message=f"Authorization successful for {client_config.name}",
        )

    except ValueError as e:
        logger.warning(f"OAuth callback validation error: {e}")
        return _render_callback_page(success=False, message=str(e))
    except Exception as e:
        logger.exception("OAuth callback error")
        return _render_callback_page(
            success=False,
            message=f"Authorization failed: {e}",
        )


@router.post("/{client_key}/revoke")
async def revoke_oauth(client_key: str) -> dict:
    """Revoke OAuth authorization for an MCP client.

    Clears the stored OAuth tokens.
    Discovery data is kept for re-authorization.
    """
    config = load_config()

    if client_key not in config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_config = config.mcp.clients[client_key]

    if not client_config.oauth_token:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' is not authorized",
        )

    # Clear token (keep discovery for re-auth)
    config.mcp.clients[client_key].oauth_token = None
    save_config(config)

    logger.info(f"OAuth authorization revoked for client '{client_key}'")
    return {"message": f"Authorization revoked for {client_config.name}"}


@router.get("/{client_key}/status", response_model=OAuthStatusResponse)
async def get_oauth_status(client_key: str) -> OAuthStatusResponse:
    """Get OAuth authorization status for an MCP client."""
    config = load_config()

    if client_key not in config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_config = config.mcp.clients[client_key]
    oauth_token = client_config.oauth_token

    if oauth_token and oauth_token.access_token:
        return OAuthStatusResponse(
            authorized=True,
            requires_auth=False,
            expires_at=oauth_token.expires_at,
        )

    return OAuthStatusResponse(
        authorized=False,
        requires_auth=client_config.requires_auth,
        expires_at=None,
    )


@router.post("/{client_key}/refresh")
async def refresh_oauth_token(client_key: str) -> dict:
    """Manually refresh OAuth token for an MCP client."""
    config = load_config()

    if client_key not in config.mcp.clients:
        raise HTTPException(404, detail=f"MCP client '{client_key}' not found")

    client_config = config.mcp.clients[client_key]

    if not client_config.oauth_discovery:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' does not have OAuth configured",
        )

    if not client_config.oauth_token:
        raise HTTPException(
            400,
            detail=f"MCP client '{client_key}' is not authorized",
        )

    try:
        handler = get_oauth_handler()
        new_token = await handler.refresh_token(
            oauth_discovery=client_config.oauth_discovery,
            oauth_token=client_config.oauth_token,
        )

        # Save new token
        config.mcp.clients[client_key].oauth_token = new_token
        save_config(config)

        logger.info(f"OAuth token refreshed for client '{client_key}'")
        return {
            "message": "Token refreshed successfully",
            "expires_at": new_token.expires_at,
        }

    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Failed to refresh token for client '{client_key}'")
        raise HTTPException(500, detail=f"Token refresh failed: {e}") from e


def _render_callback_page(success: bool, message: str) -> HTMLResponse:
    """Render HTML page for OAuth callback result."""
    status = "Success" if success else "Error"
    color = "#52c41a" if success else "#ff4d4f"
    icon = "✓" if success else "✗"

    # Escape message for safe HTML/JS rendering
    safe_message = html.escape(message)
    js_message = json.dumps(message)  # JSON-safe for JS string

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>OAuth {status} - CoPaw</title>
        <style>
            body {{
                font-family: system-ui, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: #f5f5f5;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                max-width: 400px;
            }}
            .icon {{
                font-size: 48px;
                color: {color};
                margin-bottom: 16px;
            }}
            .title {{
                font-size: 24px;
                color: #333;
                margin-bottom: 8px;
            }}
            .message {{
                color: #666;
                margin-bottom: 24px;
            }}
            .hint {{
                color: #999;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">{icon}</div>
            <div class="title">{status}</div>
            <div class="message">{safe_message}</div>
            <div class="hint">This window will close automatically...</div>
        </div>
        <script>
            // Notify opener and close window
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'mcp-oauth-callback',
                    success: {str(success).lower()},
                    message: {js_message}
                }}, '*');
            }}
            setTimeout(() => window.close(), 2000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
