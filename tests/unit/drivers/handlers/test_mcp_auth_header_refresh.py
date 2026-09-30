# -*- coding: utf-8 -*-
"""MCP driver must apply refreshed OAuth tokens to the live HTTP client.

Regression: ``_guarded_execute`` resolves credentials on every invoke, but
``MCPDriverHandler._execute`` discarded the result (``del credential``) and
kept calling through the client that was connected with the *setup-time*
Authorization header. After ``OAuth2AuthCodeProvider`` renews ``access_token``,
subsequent tool calls still used the expired Bearer token until a full
reconnect — which for streamable_http/SSE left remote MCP stuck on 401.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.types import ResolvedCredential
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.policy import PolicyContext


def _card() -> DriverCard:
    return DriverCard(
        name="remote-mcp",
        protocol="mcp",
        endpoint={
            "transport": "streamable_http",
            "url": "https://mcp.example/mcp",
        },
        enabled=True,
    )


class _FakeHttp:
    def __init__(self, headers: dict[str, str]):
        self.headers = dict(headers)


class _FakeStatelessClient:
    """Mimics HttpStatelessClient: headers + httpx client defaults."""

    def __init__(self, headers: dict[str, str]):
        self.headers = dict(headers)
        self._http = _FakeHttp(headers)
        self.is_connected = True
        self.call_tool = AsyncMock(return_value={"ok": True})
        self.list_tools = AsyncMock(return_value=[])


@pytest.mark.asyncio
async def test_execute_applies_refreshed_bearer_to_live_http_client():
    """Resolved access_token must replace connect-time Authorization."""
    handler = MCPDriverHandler(
        card=_card(),
        credential_provider=MagicMock(),
    )
    stale = {"Authorization": "Bearer stale-token"}
    client = _FakeStatelessClient(stale)
    handler._client = client

    fresh = ResolvedCredential(
        kind="oauth2_auth_code",
        secrets={"access_token": "fresh-token"},
    )
    ctx = PolicyContext(
        subject="user:1",
        driver_name="remote-mcp",
        protocol="mcp",
        operation="invoke",
    )

    await handler._execute(
        fresh,
        ctx,
        tool_name="ping",
        arguments={},
    )

    assert client.headers.get("Authorization") == "Bearer fresh-token"
    assert client._http.headers.get("Authorization") == "Bearer fresh-token"
    client.call_tool.assert_awaited_once_with("ping", {})


@pytest.mark.asyncio
async def test_execute_without_token_leaves_headers_untouched():
    handler = MCPDriverHandler(
        card=_card(),
        credential_provider=MagicMock(),
    )
    headers = {"Authorization": "Bearer keep-me", "X-Tenant": "abc"}
    client = _FakeStatelessClient(headers)
    handler._client = client

    await handler._execute(
        ResolvedCredential.EMPTY,
        PolicyContext(
            subject="user:1",
            driver_name="remote-mcp",
            protocol="mcp",
            operation="invoke",
        ),
        tool_name="ping",
        arguments={},
    )

    assert client.headers.get("Authorization") == "Bearer keep-me"
    assert client.headers.get("X-Tenant") == "abc"


class _FakeStatefulClient:
    url = "https://mcp.example/mcp"

    def __init__(self, headers: dict[str, str]):
        self.headers = dict(headers)
        self.is_connected = True
        self.reload = AsyncMock()
        self.call_tool = AsyncMock(return_value={"ok": True})


@pytest.mark.asyncio
async def test_stateful_reload_only_when_authorization_changes():
    handler = MCPDriverHandler(
        card=_card(),
        credential_provider=MagicMock(),
    )
    client = _FakeStatefulClient({"Authorization": "Bearer same-token"})
    # Pretend this is a bare HttpStatefulClient (no Auto wrapper).
    handler._client = client

    same = ResolvedCredential(
        kind="oauth2_auth_code",
        secrets={"access_token": "same-token"},
    )
    ctx = PolicyContext(
        subject="user:1",
        driver_name="remote-mcp",
        protocol="mcp",
        operation="invoke",
    )
    await handler._execute(same, ctx, tool_name="ping", arguments={})
    client.reload.assert_not_awaited()

    rotated = ResolvedCredential(
        kind="oauth2_auth_code",
        secrets={"access_token": "rotated-token"},
    )
    await handler._execute(rotated, ctx, tool_name="ping", arguments={})
    assert client.headers.get("Authorization") == "Bearer rotated-token"
    client.reload.assert_awaited_once()
