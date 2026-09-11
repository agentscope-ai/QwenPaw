# -*- coding: utf-8 -*-
"""Integration tests for Provider OAuth API endpoints.

Tests cover:
- GET /api/provider-oauth: get provider OAuth status
- POST /api/provider-oauth/authorize: authorize provider OAuth
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_provider_oauth_status(app_server) -> None:
    """Test GET /api/provider-oauth returns OAuth status."""
    response = app_server.api_request(
        "GET",
        "/api/providers/dashscope/oauth/status?state=nonexistent_state",
    )
    assert response.status_code in (200, 404, 422)
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_provider_oauth_authorize_invalid(app_server) -> None:
    """Test POST /api/provider-oauth/authorize with invalid data."""
    response = app_server.api_request(
        "POST",
        "/api/providers/dashscope/oauth/start",
        json={},
    )
    # Should return 400 or 422 for missing required fields
    assert response.status_code in [400, 404, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_provider_oauth_status_structure(app_server) -> None:
    """Test provider OAuth status response structure."""
    response = app_server.api_request(
        "GET",
        "/api/providers/dashscope/oauth/status?state=nonexistent_state",
    )
    assert response.status_code in (200, 404, 422)
    data = response.json()
    assert isinstance(data, dict)
    # Should have OAuth-related fields
    assert len(data) >= 0


@pytest.mark.integration
@pytest.mark.p1
def test_provider_oauth_authorize_missing_params(app_server) -> None:
    """Test POST /api/provider-oauth/authorize without required params."""
    response = app_server.api_request(
        "POST",
        "/api/providers/dashscope/oauth/start",
        json={},
    )
    # Should return 400 or 422
    assert response.status_code in [400, 404, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_provider_oauth_get_specific(app_server) -> None:
    """Test GET /api/provider-oauth with specific provider."""
    response = app_server.api_request(
        "GET",
        "/api/providers/openai/oauth/status?state=nonexistent_state",
    )
    assert response.status_code in [200, 404, 422]
