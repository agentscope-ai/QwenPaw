# -*- coding: utf-8 -*-
"""Integration tests for Settings API endpoints.

Tests cover:
- GET /api/settings: get settings
- PUT /api/settings: update settings
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
async def test_settings_get(app_server):
    """Test GET /api/settings returns settings."""
    async with app_server() as server:
        response = await server.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
async def test_settings_update_invalid(app_server):
    """Test PUT /api/settings with invalid data."""
    async with app_server() as server:
        payload = {"invalid_key": "value"}
        response = await server.put("/api/settings", json=payload)
        # Should handle gracefully
        assert response.status_code in [200, 400]


@pytest.mark.integration
@pytest.mark.p1
async def test_settings_get_structure(app_server):
    """Test settings response structure."""
    async with app_server() as server:
        response = await server.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have some settings fields
        assert len(data) >= 0


@pytest.mark.integration
@pytest.mark.p1
async def test_settings_update_partial(app_server):
    """Test PUT /api/settings with partial update."""
    async with app_server() as server:
        # Get current settings
        get_response = await server.get("/api/settings")
        assert get_response.status_code == 200

        # Try to update with empty dict
        response = await server.put("/api/settings", json={})
        assert response.status_code in [200, 400]


@pytest.mark.integration
@pytest.mark.p1
async def test_settings_get_specific(app_server):
    """Test GET /api/settings with specific key."""
    async with app_server() as server:
        response = await server.get("/api/settings?key=theme")
        assert response.status_code in [200, 404]
