# -*- coding: utf-8 -*-
"""OAuth metadata discovery, PKCE, and registration helpers."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class OAuthError(ValueError):
    def __init__(self, *, status_code=400, detail):
        super().__init__(detail)
        self.status = status_code


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
        OAuthError(400) on discovery failure.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        auth_server_url = await _resolve_auth_server_url(client, mcp_url)
        if not auth_server_url:
            raise OAuthError(
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
            raise OAuthError(
                status_code=400,
                detail=(
                    f"Could not retrieve authorization server metadata from "
                    f"{auth_server_url}. "
                    "Please enter auth_endpoint and token_endpoint manually."
                ),
            )

        if "token_endpoint" not in as_meta:
            raise OAuthError(
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
