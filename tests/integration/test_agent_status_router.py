# -*- coding: utf-8 -*-
"""Integration tests for Agent Status API endpoints.

Tests cover:
- GET /api/agent-status: get agent status
- GET /api/agent-status/{agent_id}: get specific agent status
"""
import pytest

from .conftest import app_server


@pytest.mark.integration
async def test_agent_status_list():
    """Test GET /api/agent-status returns agent status list."""
    async with app_server() as server:
        response = await server.get("/api/agent-status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_agent_status_get_specific():
    """Test GET /api/agent-status/{agent_id} returns specific agent status."""
    async with app_server() as server:
        # First get list to find an agent_id
        list_response = await server.get("/api/agent-status")
        assert list_response.status_code == 200
        agents = list_response.json()
        
        if len(agents) > 0:
            agent_id = agents[0].get("id") or agents[0].get("agent_id")
            if agent_id:
                response = await server.get(f"/api/agent-status/{agent_id}")
                assert response.status_code == 200


@pytest.mark.integration
async def test_agent_status_get_nonexistent():
    """Test GET /api/agent-status/{agent_id} with non-existent agent."""
    async with app_server() as server:
        response = await server.get("/api/agent-status/nonexistent-agent-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_agent_status_structure():
    """Test agent status response structure."""
    async with app_server() as server:
        response = await server.get("/api/agent-status")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            agent = data[0]
            assert isinstance(agent, dict)
            # Should have status-related fields
            assert "id" in agent or "agent_id" in agent


@pytest.mark.integration
async def test_agent_status_with_filter():
    """Test GET /api/agent-status with filter."""
    async with app_server() as server:
        response = await server.get("/api/agent-status?status=active")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
