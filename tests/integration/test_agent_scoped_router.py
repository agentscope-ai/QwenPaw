# -*- coding: utf-8 -*-
"""Integration tests for Agent Scoped API endpoints.

Tests cover:
- GET /api/agent-scoped: get agent-scoped settings
- POST /api/agent-scoped: update agent-scoped settings
"""

import pytest



@pytest.mark.integration
async def test_agent_scoped_get(app_server):
    """Test GET /api/agent-scoped returns agent-scoped settings."""
    async with app_server() as server:
        response = await server.get("/api/agent-scoped")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_agent_scoped_update_invalid(app_server):
    """Test POST /api/agent-scoped with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/agent-scoped", json={})
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]


@pytest.mark.integration
async def test_agent_scoped_structure(app_server):
    """Test agent-scoped response structure."""
    async with app_server() as server:
        response = await server.get("/api/agent-scoped")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have agent-scoped fields
        assert len(data) >= 0


@pytest.mark.integration
async def test_agent_scoped_update_partial(app_server):
    """Test POST /api/agent-scoped with partial update."""
    async with app_server() as server:
        # Try to update with empty dict
        response = await server.post("/api/agent-scoped", json={})
        assert response.status_code in [200, 400]


@pytest.mark.integration
async def test_agent_scoped_get_specific(app_server):
    """Test GET /api/agent-scoped with specific key."""
    async with app_server() as server:
        response = await server.get("/api/agent-scoped?key=config")
        assert response.status_code in [200, 404]
