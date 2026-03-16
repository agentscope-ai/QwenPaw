# -*- coding: utf-8 -*-
"""MCP OAuth 2.1 handler with auto-discovery.

Implements the MCP Authorization specification:
https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization

Flow:
1. MCP client connects, server returns 401 Unauthorized
2. Client discovers OAuth metadata from /.well-known/oauth-authorization-server
3. Client performs Dynamic Client Registration (if needed)
4. Client initiates Authorization Code flow with PKCE
5. User authorizes, callback exchanges code for tokens
6. Tokens stored and used for subsequent requests
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional, TYPE_CHECKING
from urllib.parse import quote, urlparse

import httpx

if TYPE_CHECKING:
    from ...config.config import MCPOAuthDiscovery, MCPOAuthToken

logger = logging.getLogger(__name__)

# Pending auth request timeout (10 minutes)
PENDING_AUTH_TIMEOUT = 600

# MCP protocol version header
MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class PendingAuth:
    """Stores pending OAuth authorization request data."""

    client_key: str
    code_verifier: str
    redirect_uri: str
    created_at: float


@dataclass
class OAuthMetadata:
    """OAuth 2.0 Authorization Server Metadata (RFC8414)."""

    issuer: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    registration_endpoint: str = ""
    scopes_supported: list = None
    response_types_supported: list = None
    grant_types_supported: list = None
    code_challenge_methods_supported: list = None

    def __post_init__(self):
        if self.scopes_supported is None:
            self.scopes_supported = []
        if self.response_types_supported is None:
            self.response_types_supported = []
        if self.grant_types_supported is None:
            self.grant_types_supported = []
        if self.code_challenge_methods_supported is None:
            self.code_challenge_methods_supported = []


class MCPOAuthHandler:
    """Handles MCP OAuth 2.1 flow with auto-discovery.

    Per MCP specification:
    - PKCE is REQUIRED for all clients
    - Supports Dynamic Client Registration (RFC7591)
    - Discovers endpoints via RFC8414 metadata
    """

    def __init__(self) -> None:
        """Initialize OAuth handler."""
        self._pending_auth: Dict[str, PendingAuth] = {}
        self._lock = asyncio.Lock()

    async def discover_metadata(self, mcp_server_url: str) -> OAuthMetadata:
        """Discover OAuth metadata from MCP server.

        Per MCP spec, the authorization base URL is determined by
        discarding any path component from the MCP server URL.

        Args:
            mcp_server_url: MCP server URL
                (e.g., https://api.example.com/v1/mcp)

        Returns:
            OAuthMetadata with discovered endpoints

        Raises:
            httpx.HTTPStatusError: If metadata discovery fails
        """
        # Extract base URL (discard path)
        parsed = urlparse(mcp_server_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # Try well-known endpoint first
        metadata_url = f"{base_url}/.well-known/oauth-authorization-server"

        logger.debug(f"Discovering OAuth metadata from {metadata_url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    metadata_url,
                    headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
                )
                response.raise_for_status()
                data = response.json()

                metadata = OAuthMetadata(
                    issuer=data.get("issuer", ""),
                    authorization_endpoint=data.get(
                        "authorization_endpoint",
                        "",
                    ),
                    token_endpoint=data.get("token_endpoint", ""),
                    registration_endpoint=data.get(
                        "registration_endpoint",
                        "",
                    ),
                    scopes_supported=data.get("scopes_supported", []),
                    response_types_supported=data.get(
                        "response_types_supported",
                        [],
                    ),
                    grant_types_supported=data.get(
                        "grant_types_supported",
                        [],
                    ),
                    code_challenge_methods_supported=data.get(
                        "code_challenge_methods_supported",
                        [],
                    ),
                )

                logger.info(
                    "Discovered OAuth metadata: "
                    f"auth={metadata.authorization_endpoint}",
                )
                return metadata

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Fall back to default endpoints per MCP spec
                    logger.debug(
                        "Metadata endpoint not found, using default endpoints",
                    )
                    return OAuthMetadata(
                        authorization_endpoint=f"{base_url}/authorize",
                        token_endpoint=f"{base_url}/token",
                        registration_endpoint=f"{base_url}/register",
                    )
                raise

    async def register_client(
        self,
        registration_endpoint: str,
        redirect_uris: list[str],
        client_name: str = "CoPaw MCP Client",
    ) -> tuple[str, str]:
        """Dynamically register OAuth client (RFC7591).

        Args:
            registration_endpoint: Registration endpoint URL
            redirect_uris: List of callback URIs
            client_name: Human-readable client name

        Returns:
            Tuple of (client_id, client_secret)
        """
        logger.debug(f"Registering OAuth client at {registration_endpoint}")

        registration_data = {
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # Public client
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                registration_endpoint,
                json=registration_data,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        client_id = data["client_id"]
        client_secret = data.get("client_secret", "")

        logger.info(f"Registered OAuth client: {client_id}")
        return client_id, client_secret

    def generate_auth_url(
        self,
        client_key: str,
        oauth_discovery: "MCPOAuthDiscovery",
        redirect_uri: str,
        scope: str = "",
    ) -> str:
        """Generate OAuth authorization URL with PKCE.

        Args:
            client_key: MCP client identifier
            oauth_discovery: Discovered OAuth configuration
            redirect_uri: Callback URL for OAuth flow
            scope: Requested scopes (space-separated)

        Returns:
            Authorization URL for user to visit
        """
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Generate PKCE code verifier and challenge (REQUIRED per MCP spec)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = self._generate_code_challenge(code_verifier)

        # Store pending auth request
        self._pending_auth[state] = PendingAuth(
            client_key=client_key,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            created_at=time.time(),
        )

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": oauth_discovery.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        # Add resource parameter (RFC 8707) - required by some MCP servers
        if oauth_discovery.resource:
            params["resource"] = oauth_discovery.resource

        # Add scope if provided
        if scope:
            params["scope"] = scope
        elif oauth_discovery.scopes_supported:
            params["scope"] = " ".join(oauth_discovery.scopes_supported)

        # Build query string (URL-encode values)
        query = "&".join(
            f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v
        )
        auth_url = f"{oauth_discovery.authorization_endpoint}?{query}"

        logger.debug(
            f"Generated OAuth auth URL for client '{client_key}' "
            f"with state '{state[:8]}...'",
        )
        return auth_url

    async def handle_callback(
        self,
        state: str,
        code: str,
        oauth_discovery: "MCPOAuthDiscovery",
    ) -> tuple[str, "MCPOAuthToken"]:
        """Handle OAuth callback and exchange code for tokens.

        Args:
            state: State parameter from callback
            code: Authorization code from callback
            oauth_discovery: OAuth configuration

        Returns:
            Tuple of (client_key, MCPOAuthToken)

        Raises:
            ValueError: If state is invalid or expired
            httpx.HTTPStatusError: If token exchange fails
        """
        from ...config.config import MCPOAuthToken

        # Validate and retrieve pending auth
        async with self._lock:
            pending = self._pending_auth.pop(state, None)

        if pending is None:
            raise ValueError(f"Invalid or expired OAuth state: {state[:8]}...")

        # Check timeout
        if time.time() - pending.created_at > PENDING_AUTH_TIMEOUT:
            raise ValueError(f"OAuth state expired: {state[:8]}...")

        client_key = pending.client_key
        code_verifier = pending.code_verifier
        redirect_uri = pending.redirect_uri

        logger.debug(
            f"Exchanging authorization code for client '{client_key}'",
        )

        # Exchange code for tokens
        token_data = await self._exchange_code(
            code=code,
            oauth_discovery=oauth_discovery,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

        # Build token object
        expires_in = token_data.get("expires_in", 3600)
        oauth_token = MCPOAuthToken(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", ""),
            expires_at=time.time() + expires_in,
        )

        logger.info(
            f"OAuth token obtained for client '{client_key}', "
            f"expires in {expires_in}s",
        )
        return client_key, oauth_token

    async def refresh_token(
        self,
        oauth_discovery: "MCPOAuthDiscovery",
        oauth_token: "MCPOAuthToken",
    ) -> "MCPOAuthToken":
        """Refresh an expired or expiring OAuth token.

        Args:
            oauth_discovery: OAuth configuration
            oauth_token: Current OAuth token with refresh_token

        Returns:
            New MCPOAuthToken with refreshed access_token

        Raises:
            ValueError: If no refresh token available
            httpx.HTTPStatusError: If token refresh fails
        """
        from ...config.config import MCPOAuthToken

        if not oauth_token.refresh_token:
            raise ValueError("No refresh token available")

        logger.debug("Refreshing OAuth token")

        # Build refresh request
        data = {
            "grant_type": "refresh_token",
            "refresh_token": oauth_token.refresh_token,
            "client_id": oauth_discovery.client_id,
        }

        if oauth_discovery.client_secret:
            data["client_secret"] = oauth_discovery.client_secret

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                oauth_discovery.token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            token_data = response.json()

        expires_in = token_data.get("expires_in", 3600)
        new_token = MCPOAuthToken(
            access_token=token_data["access_token"],
            refresh_token=token_data.get(
                "refresh_token",
                oauth_token.refresh_token,
            ),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", oauth_token.scope),
            expires_at=time.time() + expires_in,
        )

        logger.info(f"OAuth token refreshed, expires in {expires_in}s")
        return new_token

    def get_pending_client_key(self, state: str) -> Optional[str]:
        """Get the client key for a pending auth state.

        Args:
            state: OAuth state parameter

        Returns:
            Client key if found, None otherwise
        """
        pending = self._pending_auth.get(state)
        return pending.client_key if pending else None

    async def cleanup_expired(self) -> int:
        """Remove expired pending auth requests.

        Returns:
            Number of expired requests removed
        """
        now = time.time()
        expired_states = [
            state
            for state, pending in self._pending_auth.items()
            if now - pending.created_at > PENDING_AUTH_TIMEOUT
        ]

        async with self._lock:
            for state in expired_states:
                self._pending_auth.pop(state, None)

        if expired_states:
            logger.debug(
                f"Cleaned up {len(expired_states)} expired OAuth states",
            )

        return len(expired_states)

    async def _exchange_code(
        self,
        code: str,
        oauth_discovery: "MCPOAuthDiscovery",
        redirect_uri: str,
        code_verifier: str,
    ) -> dict:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code
            oauth_discovery: OAuth configuration
            redirect_uri: Callback URL
            code_verifier: PKCE code verifier

        Returns:
            Token response data
        """
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": oauth_discovery.client_id,
            "code_verifier": code_verifier,  # PKCE required
        }

        if oauth_discovery.client_secret:
            data["client_secret"] = oauth_discovery.client_secret

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                oauth_discovery.token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _generate_code_challenge(code_verifier: str) -> str:
        """Generate PKCE code challenge from code verifier.

        Uses SHA256 hash and base64url encoding as per RFC 7636.

        Args:
            code_verifier: Random string for PKCE

        Returns:
            Base64url-encoded SHA256 hash
        """
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# Global singleton instance
_oauth_handler: Optional[MCPOAuthHandler] = None


def get_oauth_handler() -> MCPOAuthHandler:
    """Get or create the global OAuth handler instance."""
    global _oauth_handler
    if _oauth_handler is None:
        _oauth_handler = MCPOAuthHandler()
    return _oauth_handler
