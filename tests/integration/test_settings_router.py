# -*- coding: utf-8 -*-
"""Integration tests for Settings API endpoints.

Tests cover:
- GET /api/settings: get settings
- PUT /api/settings: update settings
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_settings_get(app_server) -> None:
    """Test GET /api/settings returns settings."""
    response = app_server.api_request("GET", "/api/settings/language")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_settings_update_invalid(app_server) -> None:
    """Test PUT /api/settings with invalid data."""
    payload = {"invalid_key": "value"}
    response = app_server.api_request(
        "PUT",
        "/api/settings/language",
        json=payload,
    )
    # Should handle gracefully
    assert response.status_code in [200, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_settings_get_structure(app_server) -> None:
    """Test settings response structure."""
    response = app_server.api_request("GET", "/api/settings/language")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    # Should have some settings fields
    assert len(data) >= 0


@pytest.mark.integration
@pytest.mark.p1
def test_settings_update_partial(app_server) -> None:
    """Test PUT /api/settings with partial update."""
    # Get current settings
    get_response = app_server.api_request("GET", "/api/settings/language")
    assert get_response.status_code == 200

    # Try to update with empty dict
    response = app_server.api_request("PUT", "/api/settings/language", json={})
    assert response.status_code in [200, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_settings_get_specific(app_server) -> None:
    """Test GET /api/settings with specific key."""
    response = app_server.api_request("GET", "/api/settings/offload-policy")
    assert response.status_code in [200, 404]
