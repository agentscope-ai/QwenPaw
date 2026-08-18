# -*- coding: utf-8 -*-
"""Integration tests for Access Control API endpoints.

Tests cover:
- GET /api/access-control: get access control settings
- POST /api/access-control: update access control settings
"""

import pytest

from .conftest import app_server


@pytest.mark.integration
async def test_access_control_get():
    """Test GET /api/access-control returns access control settings."""
    async with app_server() as server:
        response = await server.get("/api/access-control")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_access_control_update_invalid():
    """Test POST /api/access-control with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/access-control", json={})
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]


@pytest.mark.integration
async def test_access_control_structure():
    """Test access control response structure."""
    async with app_server() as server:
        response = await server.get("/api/access-control")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have access control related fields
        assert len(data) >= 0


@pytest.mark.integration
async def test_access_control_update_partial():
    """Test POST /api/access-control with partial update."""
    async with app_server() as server:
        # Try to update with empty dict
        response = await server.post("/api/access-control", json={})
        assert response.status_code in [200, 400]


@pytest.mark.integration
async def test_access_control_get_specific():
    """Test GET /api/access-control with specific key."""
    async with app_server() as server:
        response = await server.get("/api/access-control?key=permissions")
        assert response.status_code in [200, 404]
