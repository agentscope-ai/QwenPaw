# -*- coding: utf-8 -*-
"""Regression tests for path-aware MCP OAuth metadata discovery."""

import httpx
import pytest

from qwenpaw.app.routers.mcp_oauth import (
    _fetch_as_metadata,
    _resolve_auth_server_url,
)


@pytest.mark.asyncio
async def test_path_aware_protected_resource_metadata_discovery() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == (
            "/.well-known/oauth-protected-resource/coop/mcp"
        ):
            return httpx.Response(
                200,
                json={
                    "resource": "https://mcp.example.com/coop/mcp",
                    "authorization_servers": ["https://mcp.example.com"],
                },
            )
        return httpx.Response(405)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await _resolve_auth_server_url(
            client,
            "https://mcp.example.com/coop/mcp",
        )

    assert result == "https://mcp.example.com"
    assert (
        "https://mcp.example.com/.well-known/"
        "oauth-protected-resource/coop/mcp"
    ) in requested


@pytest.mark.asyncio
async def test_authorization_server_metadata_discovery() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": (
                        "https://mcp.example.com/oauth/authorize"
                    ),
                    "token_endpoint": "https://mcp.example.com/oauth/token",
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await _fetch_as_metadata(
            client,
            "https://mcp.example.com",
        )

    assert result is not None
    assert result["token_endpoint"] == "https://mcp.example.com/oauth/token"
