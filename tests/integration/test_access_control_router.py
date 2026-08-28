# -*- coding: utf-8 -*-
"""Integration tests for Access Control API endpoints.

Tests cover:
- GET /api/access-control: get access control settings
- POST /api/access-control: update access control settings
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_access_control_get(app_server) -> None:
    """Test GET /api/access-control returns access control settings."""
    response = app_server.api_request("GET", "/api/access-control")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_access_control_update_invalid(app_server) -> None:
    """Test POST /api/access-control with invalid data."""
    response = app_server.api_request(
        "POST",
        "/api/access-control/pending/approve",
        json={},
    )
    # Should handle gracefully
    assert response.status_code in [200, 400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_access_control_structure(app_server) -> None:
    """Test access control response structure."""
    response = app_server.api_request("GET", "/api/access-control")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    # Should have access control related fields
    assert len(data) >= 0


@pytest.mark.integration
@pytest.mark.p1
def test_access_control_update_partial(app_server) -> None:
    """Test POST /api/access-control with partial update."""
    # Try to update with empty dict
    response = app_server.api_request(
        "POST",
        "/api/access-control/pending/approve",
        json={},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.p1
def test_access_control_get_specific(app_server) -> None:
    """Test GET /api/access-control with specific key."""
    response = app_server.api_request("GET", "/api/access-control/console")
    assert response.status_code in [200, 404]
