# -*- coding: utf-8 -*-
"""OAuth 2.1 helpers for MCP clients.

Implements the MCP authorization spec (2025-06-18) which composes:

- RFC 9728: OAuth 2.0 Protected Resource Metadata
- RFC 8414: OAuth 2.0 Authorization Server Metadata
- RFC 7591: OAuth 2.0 Dynamic Client Registration
- RFC 7636: PKCE (S256 required)
- RFC 8707: Resource Indicators

All functions are stateless utilities; pending OAuth sessions are tracked in
the ``PENDING`` registry (in-memory, ~15 min TTL).
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import logging
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Literal, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How long a pending OAuth flow (state -> verifier) stays valid.
PENDING_TTL_SECONDS = 15 * 60

# Default timeout (seconds) for outbound metadata / token / DCR calls.
DEFAULT_HTTP_TIMEOUT = 15.0

# Name advertised when performing Dynamic Client Registration.
CLIENT_NAME = "QwenPaw"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OAuthError(Exception):
    """Raised when an OAuth operation fails.

    ``code`` follows OAuth 2.0 error conventions where applicable
    (``invalid_request``, ``invalid_grant``, ``invalid_client`` etc.), or
    uses CoPaw-specific codes for non-protocol errors (``state_expired``,
    ``discovery_failed`` ...).
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Pending OAuth sessions (state -> context)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PendingOAuth:
    """In-memory pending OAuth flow context."""

    agent_id: str
    client_key: str
    code_verifier: str
    redirect_uri: str
    token_endpoint: str
    client_id: str
    client_secret: str
    resource: str
    scope: str
    mode: Literal["auto", "paste"]
    expires_at: float


PENDING: Dict[str, PendingOAuth] = {}
_PENDING_LOCK = asyncio.Lock()


async def register_pending(state: str, pending: PendingOAuth) -> None:
    """Register a pending OAuth flow keyed by ``state``."""
    async with _PENDING_LOCK:
        _expire_locked()
        PENDING[state] = pending


async def pop_pending(state: str) -> Optional[PendingOAuth]:
    """Atomically remove and return a pending flow if still valid."""
    async with _PENDING_LOCK:
        _expire_locked()
        return PENDING.pop(state, None)


def _expire_locked() -> None:
    """Drop expired pending entries (caller must hold lock)."""
    now = time.time()
    expired = [k for k, v in PENDING.items() if v.expires_at < now]
    for k in expired:
        PENDING.pop(k, None)


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def make_pkce_pair() -> tuple[str, str]:
    """Generate a (code_verifier, code_challenge_S256) pair."""
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32))
        .rstrip(b"=")
        .decode("ascii")
    )
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest(),
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def make_state() -> str:
    """Generate a cryptographically random OAuth state value."""
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Discovery (RFC 9728 + RFC 8414)
# ---------------------------------------------------------------------------


async def discover_resource_metadata(
    server_url: str,
    http: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Fetch protected-resource metadata for the given MCP server URL.

    The MCP spec recommends probing the server first and reading the
    ``WWW-Authenticate`` header for ``resource_metadata`` URL. We fall
    back to the well-known location if probing returns no header.
    """
    own_client = http is None
    client = http or httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
    try:
        metadata_url = await _probe_resource_metadata_url(server_url, client)
        if not metadata_url:
            parsed = urllib.parse.urlsplit(server_url)
            metadata_url = urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    "/.well-known/oauth-protected-resource"
                    + (parsed.path or ""),
                    "",
                    "",
                ),
            )

        resp = await client.get(metadata_url)
        if resp.status_code != 200:
            raise OAuthError(
                "discovery_failed",
                f"GET {metadata_url} returned {resp.status_code}",
            )
        return resp.json()
    finally:
        if own_client:
            await client.aclose()


async def _probe_resource_metadata_url(
    server_url: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Probe the MCP server and parse 401 WWW-Authenticate."""
    try:
        resp = await client.post(
            server_url,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": "probe"},
                },
            },
        )
    except httpx.HTTPError as e:
        logger.debug("Probe request failed for %s: %s", server_url, e)
        return None

    if resp.status_code != 401:
        return None

    www_auth = resp.headers.get("www-authenticate") or resp.headers.get(
        "WWW-Authenticate",
    )
    if not www_auth:
        return None

    return _parse_resource_metadata_from_www_auth(www_auth)


def _parse_resource_metadata_from_www_auth(header: str) -> Optional[str]:
    """Extract ``resource_metadata`` parameter from WWW-Authenticate header."""
    for token in header.split(","):
        token = token.strip()
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.split(" ", 1)[-1].strip().lower()
        if key == "resource_metadata":
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value
    return None


async def discover_authorization_server(
    issuer: str,
    http: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Fetch authorization-server metadata via RFC 8414 well-known URL."""
    parsed = urllib.parse.urlsplit(issuer)
    metadata_url = urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            "/.well-known/oauth-authorization-server" + (parsed.path or ""),
            "",
            "",
        ),
    )

    own_client = http is None
    client = http or httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
    try:
        resp = await client.get(metadata_url)
        if resp.status_code != 200:
            raise OAuthError(
                "discovery_failed",
                f"GET {metadata_url} returned {resp.status_code}",
            )
        return resp.json()
    finally:
        if own_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------


async def dynamic_client_register(
    registration_endpoint: str,
    redirect_uris: List[str],
    http: Optional[httpx.AsyncClient] = None,
    client_name: str = CLIENT_NAME,
) -> Dict[str, Any]:
    """Register a new OAuth client and return AS-issued credentials."""
    payload = {
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }

    own_client = http is None
    client = http or httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
    try:
        resp = await client.post(
            registration_endpoint,
            json=payload,
        )
        if resp.status_code not in (200, 201):
            raise OAuthError(
                "registration_failed",
                f"DCR returned {resp.status_code}: {resp.text[:200]}",
            )
        return resp.json()
    finally:
        if own_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Authorize URL
# ---------------------------------------------------------------------------


def build_authorize_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    resource: str = "",
    scope: str = "",
) -> str:
    """Construct an OAuth authorize URL with PKCE and (optional) resource."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if resource:
        params["resource"] = resource
    if scope:
        params["scope"] = scope

    sep = "&" if "?" in authorization_endpoint else "?"
    return authorization_endpoint + sep + urllib.parse.urlencode(params)


# ---------------------------------------------------------------------------
# Token exchange / refresh
# ---------------------------------------------------------------------------


async def exchange_code(
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str = "",
    http: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Exchange an authorization code for an access token + refresh token."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    own_client = http is None
    client = http or httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
    try:
        resp = await client.post(
            token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            _raise_token_error(resp)
        return resp.json()
    finally:
        if own_client:
            await client.aclose()


async def refresh_access_token(
    token_endpoint: str,
    refresh_token: str,
    client_id: str,
    client_secret: str = "",
    http: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Exchange a refresh token for a fresh access token."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    own_client = http is None
    client = http or httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
    try:
        resp = await client.post(
            token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            _raise_token_error(resp)
        return resp.json()
    finally:
        if own_client:
            await client.aclose()


async def revoke_token(
    revocation_endpoint: str,
    token: str,
    token_type_hint: Literal["access_token", "refresh_token"],
    client_id: str,
    client_secret: str = "",
    http: Optional[httpx.AsyncClient] = None,
) -> None:
    """Best-effort RFC 7009 revocation. Errors are logged but not raised."""
    data = {
        "token": token,
        "token_type_hint": token_type_hint,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    own_client = http is None
    client = http or httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
    try:
        resp = await client.post(
            revocation_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            logger.info(
                "Revocation returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
    except httpx.HTTPError as e:
        logger.info("Revocation request failed: %s", e)
    finally:
        if own_client:
            await client.aclose()


def _raise_token_error(resp: httpx.Response) -> None:
    """Raise OAuthError parsed from an RFC 6749 token error response."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    code = body.get("error") or f"http_{resp.status_code}"
    message = body.get("error_description") or resp.text[:200]
    raise OAuthError(code, message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_token_expires_at(expires_in: Any) -> int:
    """Convert OAuth ``expires_in`` (seconds) to absolute unix timestamp.

    Returns 0 when ``expires_in`` is missing/invalid; callers should treat
    0 as "unknown expiry" (and prefer 401-driven refresh).
    """
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return int(time.time()) + seconds


def parse_callback_url(callback_url: str) -> Dict[str, str]:
    """Extract OAuth params from a callback URL (query or fragment)."""
    parsed = urllib.parse.urlsplit(callback_url.strip())
    params: Dict[str, str] = {}
    if parsed.query:
        params.update(dict(urllib.parse.parse_qsl(parsed.query)))
    if parsed.fragment:
        params.update(dict(urllib.parse.parse_qsl(parsed.fragment)))
    return params
