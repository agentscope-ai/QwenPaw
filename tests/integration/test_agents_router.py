# -*- coding: utf-8 -*-
"""Integration tests for Agents API endpoints.

Tests cover:
- GET /api/agents: list agents (returns {"agents": [...]})
- GET /api/agents/{agent_id}: get agent details
- POST /api/agents: create agent
"""

import pytest
from helpers import default_http_timeout

_AGENTS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_agents_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents returns an AgentListResponse with an
      ``agents`` array.

    API endpoints:
    - GET /api/agents
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents",
        timeout=_AGENTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, dict)
    assert isinstance(data.get("agents"), list)


@pytest.mark.integration
@pytest.mark.p1
def test_agents_get_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents/{agent_id} with a non-existent id returns 404.

    API endpoints:
    - GET /api/agents/{agentId}
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents/nonexistent-agent-12345",
        timeout=_AGENTS_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_agents_create_invalid(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents with an empty body is rejected (4xx).

    API endpoints:
    - POST /api/agents
    """
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={},
        timeout=_AGENTS_TIMEOUT,
    )
    assert resp.status_code in (400, 409, 422), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_agents_list_item_schema(app_server) -> None:
    """Test purpose:
    - Verify each agent entry carries an identifier field.

    API endpoints:
    - GET /api/agents
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents",
        timeout=_AGENTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    agents = resp.json().get("agents", [])
    assert len(agents) > 0
    agent = agents[0]
    assert isinstance(agent, dict)
    assert "id" in agent or "name" in agent or "agent_id" in agent


@pytest.mark.integration
@pytest.mark.p1
def test_agents_get_default(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents/default returns the default agent profile.

    API endpoints:
    - GET /api/agents/{agentId}
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents/default",
        timeout=_AGENTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, dict)
