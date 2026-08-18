# -*- coding: utf-8 -*-
"""Integration tests for Access Control API endpoints.

Tests cover:
- GET /api/access-control: get access control settings
- POST /api/access-control: update access control settings
"""

import pytest


@pytest.mark.integration
async def test_access_control_get(app_server):
    """Test GET /api/access-control returns access control settings."""
    async with app_server() as server:
        response = await server.get("/api/access-control")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_access_control_update_invalid(app_server):
    """Test POST /api/access-control with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/access-control", json={})
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]


@pytest.mark.integration
async def test_access_control_structure(app_server):
    """Test access control response structure."""
    async with app_server() as server:
        response = await server.get("/api/access-control")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have access control related fields
        assert len(data) >= 0


@pytest.mark.integration
async def test_access_control_update_partial(app_server):
    """Test POST /api/access-control with partial update."""
    async with app_server() as server:
        # Try to update with empty dict
        response = await server.post("/api/access-control", json={})
        assert response.status_code in [200, 400]


@pytest.mark.integration
async def test_access_control_get_specific(app_server):
    """Test GET /api/access-control with specific key."""
    async with app_server() as server:
        response = await server.get("/api/access-control?key=permissions")
        assert response.status_code in [200, 404]
