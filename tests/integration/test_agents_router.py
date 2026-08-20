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
@pytest.mark.p1
def test_agents_list(app_server) -> None:
    """Test GET /api/agents returns agent list."""
    response = app_server.api_request("GET", "/api/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_agents_get_nonexistent(app_server) -> None:
    """Test GET /api/agents/{agent_id} with non-existent agent."""
    response = app_server.api_request("GET", "/api/agents/nonexistent-agent-12345")
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_agents_create_invalid(app_server) -> None:
    """Test POST /api/agents with invalid data."""
    response = app_server.api_request("POST", "/api/agents", json={})
    # Should return 400 or 422 for missing required fields
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_agents_delete_nonexistent(app_server) -> None:
    """Test DELETE /api/agents/{agent_id} with non-existent agent."""
    response = app_server.api_request("DELETE", "/api/agents/nonexistent-agent-12345")
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_agents_list_pagination(app_server) -> None:
    """Test agents list pagination."""
    response = app_server.api_request("GET", "/api/agents?limit=5&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.p1
def test_agents_structure(app_server) -> None:
    """Test agent response structure."""
    response = app_server.api_request("GET", "/api/agents")
    assert response.status_code == 200
    data = response.json()
    if len(data) > 0:
        agent = data[0]
        assert isinstance(agent, dict)
        # Should have id or name field
        assert "id" in agent or "name" in agent or "agent_id" in agent


@pytest.mark.integration
@pytest.mark.p1
def test_agents_list_with_filter(app_server) -> None:
    """Test GET /api/agents with filter."""
    response = app_server.api_request("GET", "/api/agents?status=active")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
