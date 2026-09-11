# -*- coding: utf-8 -*-
"""Integration tests for the MCP console-management surface.

Third coverage-sprint batch, targeted at uncovered lines in
src/qwenpaw/app/mcp/config_service.py (policy update path, access
principals, tool whitelist update).

Tests cover:
- GET  /api/mcp/policy/{client_key}: unknown client 404
- PUT  /api/mcp/policy/{client_key}: unknown client 404; empty tool name 400
- GET  /api/mcp/access-principals: recent principals list
- GET  /api/mcp/tools/{client_key}: unknown client error path
- PUT  /api/mcp/tools/{client_key}: unknown client error path
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_MCP_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_policy_get_unknown_client(app_server) -> None:
    """Test purpose:
    - Verify reading the saved policy of an unknown MCP client yields 404.

    API endpoints:
    - GET /api/mcp/policy/{client_key}
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/policy/integ-unknown-mcp-client",
        timeout=_MCP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_policy_put_unknown_client(app_server) -> None:
    """Test purpose:
    - Verify updating the policy of an unknown MCP client yields 404.

    API endpoints:
    - PUT /api/mcp/policy/{client_key}
    """
    resp = app_server.api_request(
        "PUT",
        "/api/mcp/policy/integ-unknown-mcp-client",
        json={"default_effect": "deny", "tool_defaults": []},
        timeout=_MCP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_policy_put_invalid_body(app_server) -> None:
    """Test purpose:
    - Verify a policy body with an invalid effect is rejected (422).

    API endpoints:
    - PUT /api/mcp/policy/{client_key}
    """
    resp = app_server.api_request(
        "PUT",
        "/api/mcp/policy/integ-unknown-mcp-client",
        json={"default_effect": "bogus-effect"},
        timeout=_MCP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_access_principals_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/mcp/access-principals returns a list payload.

    API endpoints:
    - GET /api/mcp/access-principals
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/access-principals",
        timeout=_MCP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_tools_get_unknown_client(app_server) -> None:
    """Test purpose:
    - Verify listing tools of an unknown MCP client yields an error.

    API endpoints:
    - GET /api/mcp/tools/{client_key}
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/tools/integ-unknown-mcp-client",
        timeout=_MCP_TIMEOUT,
    )
    assert resp.status_code in (404, 400), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_tools_put_unknown_client(app_server) -> None:
    """Test purpose:
    - Verify updating the tool whitelist of an unknown client errors.

    API endpoints:
    - PUT /api/mcp/tools/{client_key}
    """
    resp = app_server.api_request(
        "PUT",
        "/api/mcp/tools/integ-unknown-mcp-client",
        json={"tools": ["some_tool"]},
        timeout=_MCP_TIMEOUT,
    )
    assert resp.status_code in (404, 400), app_server.logs_tail()
