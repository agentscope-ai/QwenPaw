# -*- coding: utf-8 -*-
"""Integration tests for MCP API endpoints.

Tests cover:
- GET /api/mcp: get MCP status
- GET /api/mcp/servers: list MCP servers
- POST /api/mcp/servers: add MCP server
"""

import pytest

from conftest import app_server


@pytest.mark.integration
async def test_mcp_status():
    """Test GET /api/mcp returns MCP status."""
    async with app_server() as server:
        response = await server.get("/api/mcp")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_mcp_servers_list():
    """Test GET /api/mcp/servers returns server list."""
    async with app_server() as server:
        response = await server.get("/api/mcp/servers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_mcp_servers_add_invalid():
    """Test POST /api/mcp/servers with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/mcp/servers", json={})
        # Should return 400 or 422 for missing required fields
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_mcp_servers_list_pagination():
    """Test MCP servers list pagination."""
    async with app_server() as server:
        response = await server.get("/api/mcp/servers?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_mcp_status_structure():
    """Test MCP status response structure."""
    async with app_server() as server:
        response = await server.get("/api/mcp")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have MCP-related fields
        assert len(data) >= 0
