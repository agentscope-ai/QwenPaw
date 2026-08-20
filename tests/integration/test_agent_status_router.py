# -*- coding: utf-8 -*-
"""Integration tests for Agent Status API endpoints.

Tests cover:
- GET /api/agent-status: get agent status
- GET /api/agent-status/{agent_id}: get specific agent status
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_list(app_server) -> None:
    """Test GET /api/agent-status returns agent status list."""
    response = app_server.api_request("GET", "/api/agent-status")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_get_specific(app_server) -> None:
    """Test GET /api/agent-status/{agent_id} returns specific agent status."""
    # First get list to find an agent_id
    list_response = app_server.api_request("GET", "/api/agent-status")
    assert list_response.status_code == 200
    agents = list_response.json()

    if len(agents) > 0:
        agent_id = agents[0].get("id") or agents[0].get("agent_id")
        if agent_id:
            response = app_server.api_request("GET", f"/api/agent-status/{agent_id}")
            assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_get_nonexistent(app_server) -> None:
    """Test GET /api/agent-status/{agent_id} with non-existent agent."""
    url = "/api/agent-status/nonexistent-agent-12345"
    response = app_server.api_request("GET", url)
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_structure(app_server) -> None:
    """Test agent status response structure."""
    response = app_server.api_request("GET", "/api/agent-status")
    assert response.status_code == 200
    data = response.json()
    if len(data) > 0:
        agent = data[0]
        assert isinstance(agent, dict)
        # Should have status-related fields
        assert "id" in agent or "agent_id" in agent


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_with_filter(app_server) -> None:
    """Test GET /api/agent-status with filter."""
    response = app_server.api_request("GET", "/api/agent-status?status=active")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
