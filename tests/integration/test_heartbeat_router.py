# -*- coding: utf-8 -*-
"""Integration tests for the heartbeat endpoint.

Covers GET /api/agents/{agentId}/config/heartbeat.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout, create_agent, delete_agent_quietly

_HEARTBEAT_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents/{agentId}/config/heartbeat returns
      heartbeat configuration. Console uses this for keepalive settings.

    Test flow:
    1. Create test agent.
    2. GET heartbeat config.
    3. Assert 200 and response is a dict.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/heartbeat
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_heartbeat_test_01"
    create_agent(app_server, agent_id)

    try:
        resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/config/heartbeat",
            timeout=_HEARTBEAT_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        payload = resp.json()
        assert isinstance(payload, dict)
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_nonexistent_agent(app_server) -> None:
    """Test purpose:
    - Verify GET heartbeat for nonexistent agent returns 404.

    Test flow:
    1. GET heartbeat for nonexistent agent.
    2. Assert 404.

    API endpoints:
    - GET /api/agents/{agentId}/config/heartbeat
    """
    resp = app_server.api_request(
        "GET",
        "/api/agents/nonexistent_agent_xyz/config/heartbeat",
        timeout=_HEARTBEAT_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_put(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/agents/{agentId}/config/heartbeat accepts valid
      heartbeat configuration.

    Test flow:
    1. Create test agent.
    2. PUT heartbeat config.
    3. Assert 200.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/config/heartbeat
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_heartbeat_test_02"
    create_agent(app_server, agent_id)

    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/config/heartbeat",
            json={"enabled": True, "interval_seconds": 30},
            timeout=_HEARTBEAT_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
    finally:
        delete_agent_quietly(app_server, agent_id)
