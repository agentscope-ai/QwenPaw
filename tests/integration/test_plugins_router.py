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
async def test_plugins_list(app_server):
    """Test GET /api/plugins returns plugin list."""
    async with app_server() as server:
        response = await server.get("/api/plugins")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_plugins_available(app_server):
    """Test GET /api/plugins/available returns available plugins."""
    async with app_server() as server:
        response = await server.get("/api/plugins/available")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_plugins_list_with_status_filter(app_server):
    """Test GET /api/plugins with status filter."""
    async with app_server() as server:
        # Filter by installed status
        response = await server.get("/api/plugins?installed=true")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_plugins_get_nonexistent(app_server):
    """Test GET /api/plugins/{plugin_id} with non-existent plugin."""
    async with app_server() as server:
        response = await server.get("/api/plugins/nonexistent-plugin-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_plugins_install_invalid(app_server):
    """Test POST /api/plugins/install with invalid plugin."""
    async with app_server() as server:
        response = await server.post(
            "/api/plugins/install",
            json={"plugin_id": "no-such-plugin"},
        )
        # Should fail gracefully
        assert response.status_code in [400, 404, 422]


@pytest.mark.integration
async def test_plugins_uninstall_nonexistent(app_server):
    """Test DELETE /api/plugins/{plugin_id} with non-existent plugin."""
    async with app_server() as server:
        response = await server.delete("/api/plugins/nonexistent-plugin-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_plugins_list_pagination(app_server):
    """Test plugins list pagination."""
    async with app_server() as server:
        response = await server.get("/api/plugins?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5
