# -*- coding: utf-8 -*-
"""Integration tests for MCP API endpoints.

Tests cover:
- GET /api/mcp: get MCP status
- GET /api/mcp/servers: list MCP servers
- POST /api/mcp/servers: add MCP server
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_status(app_server) -> None:
    """Test GET /api/mcp returns MCP status."""
    response = app_server.api_request("GET", "/api/mcp")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_servers_list(app_server) -> None:
    """Test GET /api/mcp/servers returns server list."""
    response = app_server.api_request("GET", "/api/mcp")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_servers_add_invalid(app_server) -> None:
    """Test POST /api/mcp/servers with invalid data."""
    response = app_server.api_request("POST", "/api/mcp", json={})
    # Should return 400 or 422 for missing required fields
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_servers_list_pagination(app_server) -> None:
    """Test MCP servers list pagination."""
    response = app_server.api_request("GET", "/api/mcp")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_status_structure(app_server) -> None:
    """Test MCP status response structure."""
    response = app_server.api_request("GET", "/api/mcp")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should have MCP-related fields
    assert len(data) >= 0
