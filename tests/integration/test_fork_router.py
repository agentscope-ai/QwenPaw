# -*- coding: utf-8 -*-
"""Integration tests for Fork API endpoints.

Tests cover:
- GET /api/fork: get fork status
- POST /api/fork: create fork
- GET /api/fork/list: list forks
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_fork_status(app_server) -> None:
    """Test GET /api/fork returns fork status."""
    response = app_server.api_request("GET", "/api/fork/agent")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_fork_list(app_server) -> None:
    """Test GET /api/fork/list returns fork list."""
    response = app_server.api_request("GET", "/api/fork/list")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_fork_create_invalid(app_server) -> None:
    """Test POST /api/fork with invalid request."""
    response = app_server.api_request("POST", "/api/fork/agent", json={})
    # Should return 400 or 422 for missing required fields
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_fork_list_pagination(app_server) -> None:
    """Test fork list pagination."""
    response = app_server.api_request("GET", "/api/fork/list?limit=5&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.p1
def test_fork_list_empty_filter(app_server) -> None:
    """Test fork list with empty filter."""
    response = app_server.api_request("GET", "/api/fork/list?status=")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
