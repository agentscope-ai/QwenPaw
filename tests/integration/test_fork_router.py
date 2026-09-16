# -*- coding: utf-8 -*-
"""Integration tests for the Fork API endpoint.

Upstream ships exactly one fork route: POST /api/fork/agent (internal,
localhost-only, used by spawn_subagent(fork=True)). It creates a fork
session file (and a git worktree when the project dir is a repo) and
returns the fork identifiers.

Tests cover:
- POST /api/fork/agent: create a fork session for an absent parent
- POST /api/fork/agent: validation errors for missing fields
"""

import pytest
from helpers import default_http_timeout

_FORK_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_fork_agent_creates_fork_session(app_server) -> None:
    """Test purpose:
    - Verify POST /api/fork/agent with a complete body returns the fork
      identifiers (fork_session_id / worktree fields).

    API endpoints:
    - POST /api/fork/agent
    """
    resp = app_server.api_request(
        "POST",
        "/api/fork/agent",
        json={
            "agent_id": "default",
            "parent_session_id": "integ-nonexistent-parent",
        },
        timeout=_FORK_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert "fork_session_id" in data


@pytest.mark.integration
@pytest.mark.p1
def test_fork_agent_empty_body_rejected(app_server) -> None:
    """Test purpose:
    - Verify POST /api/fork/agent with an empty body is rejected (422).

    API endpoints:
    - POST /api/fork/agent
    """
    resp = app_server.api_request(
        "POST",
        "/api/fork/agent",
        json={},
        timeout=_FORK_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_fork_agent_missing_parent_rejected(app_server) -> None:
    """Test purpose:
    - Verify POST /api/fork/agent without parent_session_id is rejected.

    API endpoints:
    - POST /api/fork/agent
    """
    resp = app_server.api_request(
        "POST",
        "/api/fork/agent",
        json={"agent_id": "default"},
        timeout=_FORK_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()
