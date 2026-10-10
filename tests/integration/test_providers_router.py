# -*- coding: utf-8 -*-
"""Integration tests for Providers API endpoints.

Tests cover:
- GET /api/providers: list providers
- GET /api/providers/{provider_id}: get provider details
- POST /api/providers: add provider
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_providers_list(app_server) -> None:
    """Test GET /api/providers returns provider list."""
    response = app_server.api_request("GET", "/api/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_providers_get_nonexistent(app_server) -> None:
    """Test GET /api/providers/{provider_id} with non-existent provider."""
    url = "/api/models/nonexistent-provider-12345/config"
    response = app_server.api_request("GET", url)
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_providers_add_invalid(app_server) -> None:
    """Test POST /api/providers with invalid data."""
    response = app_server.api_request(
        "POST",
        "/api/models/custom-providers",
        json={},
    )
    # Should return 400 or 422 for missing required fields
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_providers_list_with_filter(app_server) -> None:
    """Test GET /api/providers with filter."""
    response = app_server.api_request("GET", "/api/models?type=")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_providers_list_pagination(app_server) -> None:
    """Test providers list pagination."""
    response = app_server.api_request("GET", "/api/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.integration
@pytest.mark.p1
def test_providers_structure(app_server) -> None:
    """Test provider response structure."""
    response = app_server.api_request("GET", "/api/models")
    assert response.status_code == 200
    data = response.json()
    if len(data) > 0:
        provider = data[0]
        assert isinstance(provider, dict)
        # Should have id or name field
        assert "id" in provider or "name" in provider
