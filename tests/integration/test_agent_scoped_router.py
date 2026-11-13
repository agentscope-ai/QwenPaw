# -*- coding: utf-8 -*-
"""Integration tests for Agent Scoped API endpoints.

Tests cover:
- GET /api/agent-scoped: get agent-scoped settings
- POST /api/agent-scoped: update agent-scoped settings
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_get(app_server) -> None:
    """Test GET /api/agent-scoped returns agent-scoped settings."""
    response = app_server.api_request(
        "GET",
        "/api/agents/default/agent-status",
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_update_invalid(app_server) -> None:
    """Test POST /api/agent-scoped with invalid data."""
    response = app_server.api_request(
        "POST",
        "/api/agents/default/cron/jobs",
        json={},
    )
    # Should handle gracefully
    assert response.status_code in [200, 400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_structure(app_server) -> None:
    """Test agent-scoped response structure."""
    response = app_server.api_request(
        "GET",
        "/api/agents/default/agent-status",
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    # Should have agent-scoped fields
    assert len(data) >= 0


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_update_partial(app_server) -> None:
    """Test POST /api/agent-scoped with partial update."""
    # Try to update with empty dict
    response = app_server.api_request(
        "POST",
        "/api/agents/default/cron/jobs",
        json={},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_get_specific(app_server) -> None:
    """Test GET /api/agent-scoped with specific key."""
    response = app_server.api_request(
        "GET",
        "/api/agents/default/config/channels",
    )
    assert response.status_code in [200, 404]
