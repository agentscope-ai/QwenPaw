# -*- coding: utf-8 -*-
"""Integration tests for Agent Status API endpoints.

The agent-status router is mounted under the agent-scoped prefix, so the
real path is /api/agents/{agentId}/agent-status.

Tests cover:
- GET /api/agents/{agentId}/agent-status: get agent runtime status
"""

import pytest
from helpers import default_http_timeout

_STATUS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents/default/agent-status returns runtime status.

    API endpoints:
    - GET /api/agents/{agentId}/agent-status
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents/default/agent-status",
        timeout=_STATUS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_structure(app_server) -> None:
    """Test purpose:
    - Verify the status payload is a dict with runtime fields.

    API endpoints:
    - GET /api/agents/{agentId}/agent-status
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents/default/agent-status",
        timeout=_STATUS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, dict)
    assert len(data) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_agent_status_second_agent(app_server) -> None:
    """Test purpose:
    - Verify the status endpoint also serves the bundled QA agent.

    API endpoints:
    - GET /api/agents/{agentId}/agent-status
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents/QwenPaw_QA_Agent_0.2/agent-status",
        timeout=_STATUS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
