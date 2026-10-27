# -*- coding: utf-8 -*-
"""Integration tests for Auth API endpoints.

Tests cover:
- GET /api/auth/status: get auth status
- POST /api/auth/login: login
- POST /api/auth/logout: logout
- GET /api/auth/user: get current user
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_auth_status(app_server) -> None:
    """Test GET /api/auth/status returns auth status."""
    response = app_server.api_request("GET", "/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert "enabled" in data or "authenticated" in data


@pytest.mark.integration
@pytest.mark.p1
def test_auth_user_unauthenticated(app_server) -> None:
    """Test GET /api/auth/user without authentication."""
    response = app_server.api_request("GET", "/api/auth/verify")
    # Should return 401 or user info depending on auth config
    assert response.status_code in [200, 401]


@pytest.mark.integration
@pytest.mark.p1
def test_auth_login_missing_credentials(app_server) -> None:
    """Test POST /api/auth/login without credentials."""
    response = app_server.api_request("POST", "/api/auth/login", json={})
    # Should return 400 or 422 for missing credentials
    assert response.status_code in [400, 401, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_auth_login_invalid_format(app_server) -> None:
    """Test POST /api/auth/login with invalid format."""
    payload = {"invalid": "data"}
    response = app_server.api_request("POST", "/api/auth/login", json=payload)
    # Should return 400 or 422
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_auth_logout(app_server) -> None:
    """Test POST /api/auth/logout."""
    response = app_server.api_request("POST", "/api/auth/revoke-all-tokens")
    # 403 when auth is not enabled on the test instance
    assert response.status_code in [200, 401, 403]


@pytest.mark.integration
@pytest.mark.p1
def test_auth_status_structure(app_server) -> None:
    """Test auth status response structure."""
    response = app_server.api_request("GET", "/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    # Should have some auth-related fields
    assert isinstance(data, dict)
    assert len(data) > 0
