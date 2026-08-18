# -*- coding: utf-8 -*-
"""Integration tests for Agents API endpoints.

Tests cover:
- GET /api/agents: list agents
- GET /api/agents/{agent_id}: get agent details
- POST /api/agents: create agent
- DELETE /api/agents/{agent_id}: delete agent
"""

import pytest


@pytest.mark.integration
async def test_agents_list(app_server):
    """Test GET /api/agents returns agent list."""
    async with app_server() as server:
        response = await server.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_agents_get_nonexistent(app_server):
    """Test GET /api/agents/{agent_id} with non-existent agent."""
    async with app_server() as server:
        response = await server.get("/api/agents/nonexistent-agent-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_agents_create_invalid(app_server):
    """Test POST /api/agents with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/agents", json={})
        # Should return 400 or 422 for missing required fields
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_agents_delete_nonexistent(app_server):
    """Test DELETE /api/agents/{agent_id} with non-existent agent."""
    async with app_server() as server:
        response = await server.delete("/api/agents/nonexistent-agent-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_agents_list_pagination(app_server):
    """Test agents list pagination."""
    async with app_server() as server:
        response = await server.get("/api/agents?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_agents_structure(app_server):
    """Test agent response structure."""
    async with app_server() as server:
        response = await server.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            agent = data[0]
            assert isinstance(agent, dict)
            # Should have id or name field
            assert "id" in agent or "name" in agent or "agent_id" in agent


@pytest.mark.integration
async def test_agents_list_with_filter(app_server):
    """Test GET /api/agents with filter."""
    async with app_server() as server:
        response = await server.get("/api/agents?status=active")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
