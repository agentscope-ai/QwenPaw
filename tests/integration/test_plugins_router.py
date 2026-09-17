# -*- coding: utf-8 -*-
"""Integration tests for Plugins API endpoints.

Tests cover:
- GET /api/plugins: list installed plugins
- GET /api/plugins/available: list available plugins
- POST /api/plugins/install: install a plugin
- DELETE /api/plugins/{plugin_id}: uninstall a plugin
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_list(app_server) -> None:
    """Test GET /api/plugins returns plugin list."""
    response = app_server.api_request("GET", "/api/plugins")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_available(app_server) -> None:
    """Test GET /api/plugins/available returns available plugins."""
    response = app_server.api_request("GET", "/api/plugins/catalog")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert isinstance(data.get("plugins"), list)


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_list_with_status_filter(app_server) -> None:
    """Test GET /api/plugins with status filter."""
    # Filter by installed status
    response = app_server.api_request("GET", "/api/plugins?installed=true")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_get_nonexistent(app_server) -> None:
    """Test GET /api/plugins/{plugin_id} with non-existent plugin."""
    response = app_server.api_request(
        "GET",
        "/api/plugins/nonexistent-plugin-12345",
    )
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_install_invalid(app_server) -> None:
    """Test POST /api/plugins/install with invalid plugin."""
    response = app_server.api_request(
        "POST",
        "/api/plugins/install",
        json={"plugin_id": "no-such-plugin"},
    )
    # Should fail gracefully
    assert response.status_code in [400, 404, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_uninstall_nonexistent(app_server) -> None:
    """Test DELETE /api/plugins/{plugin_id} with non-existent plugin."""
    response = app_server.api_request(
        "DELETE",
        "/api/plugins/nonexistent-plugin-12345",
    )
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_plugins_list_pagination(app_server) -> None:
    """Test plugins list pagination."""
    response = app_server.api_request("GET", "/api/plugins?limit=5&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5
