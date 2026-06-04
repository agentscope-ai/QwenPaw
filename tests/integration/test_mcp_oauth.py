# -*- coding: utf-8 -*-
"""Integration tests for the MCP OAuth 2.1 router."""
from __future__ import annotations

import pytest

_MCP_OAUTH_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p2
def test_mcp_oauth_status_returns_404_for_missing_client(app_server) -> None:
    """Test purpose:
    - Verify GET /api/mcp/oauth/status/{client_key} returns 404 when the
      MCP client does not exist for the active agent, so Console doesn't
      silently treat an unknown client as unauthorised.

    Test flow:
    1. GET /api/mcp/oauth/status/<unknown-client>.
    2. Assert 404 status with detail mentioning the missing client.

    API endpoints:
    - GET /api/mcp/oauth/status/{client_key:path}
    """
    unknown_client = "integ_oauth_status_missing_client"
    resp = app_server.api_request(
        "GET",
        f"/api/mcp/oauth/status/{unknown_client}",
        timeout=_MCP_OAUTH_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert unknown_client in detail or "not found" in detail.lower()


@pytest.mark.integration
@pytest.mark.p2
def test_mcp_oauth_revoke_returns_404_for_missing_client(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/mcp/oauth/{client_key} returns 404 when the MCP
      client does not exist (logout / re-auth prep should fail loudly
      rather than appearing to succeed).

    Test flow:
    1. DELETE /api/mcp/oauth/<unknown-client>.
    2. Assert 404 status with detail mentioning the missing client.

    API endpoints:
    - DELETE /api/mcp/oauth/{client_key:path}
    """
    unknown_client = "integ_oauth_revoke_missing_client"
    resp = app_server.api_request(
        "DELETE",
        f"/api/mcp/oauth/{unknown_client}",
        timeout=_MCP_OAUTH_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert unknown_client in detail or "not found" in detail.lower()


@pytest.mark.integration
@pytest.mark.p2
def test_mcp_oauth_callback_with_error_param_returns_html_400(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/mcp/oauth/callback returns an HTML error page with
      400 status when the IdP redirected back with ``error=...``. The
      popup uses localStorage + postMessage to notify the opener; the
      body should expose the error description for visibility.

    Test flow:
    1. GET /api/mcp/oauth/callback?error=access_denied&error_description=...
    2. Assert 400 status, HTML content type, and the error description
       is rendered in the body.

    API endpoints:
    - GET /api/mcp/oauth/callback
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/oauth/callback",
        params={
            "error": "access_denied",
            "error_description": "Test denied by user",
        },
        timeout=_MCP_OAUTH_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    content_type = resp.headers.get("content-type", "")
    assert "html" in content_type.lower(), content_type
    assert "Test denied by user" in resp.text
