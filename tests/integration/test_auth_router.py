# -*- coding: utf-8 -*-
"""Integration tests for Auth API endpoints.

Tests cover:
- GET /api/auth/status: get auth status
- POST /api/auth/login: login
- POST /api/auth/logout: logout
- GET /api/auth/user: get current user
"""

import pytest

from conftest import app_server


@pytest.mark.integration
async def test_auth_status():
    """Test GET /api/auth/status returns auth status."""
    async with app_server() as server:
        response = await server.get("/api/auth/status")
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data or "authenticated" in data


@pytest.mark.integration
async def test_auth_user_unauthenticated():
    """Test GET /api/auth/user without authentication."""
    async with app_server() as server:
        response = await server.get("/api/auth/user")
        # Should return 401 or user info depending on auth config
        assert response.status_code in [200, 401]


@pytest.mark.integration
async def test_auth_login_missing_credentials():
    """Test POST /api/auth/login without credentials."""
    async with app_server() as server:
        response = await server.post("/api/auth/login", json={})
        # Should return 400 or 422 for missing credentials
        assert response.status_code in [400, 401, 422]


@pytest.mark.integration
async def test_auth_login_invalid_format():
    """Test POST /api/auth/login with invalid format."""
    async with app_server() as server:
        payload = {"invalid": "data"}
        response = await server.post("/api/auth/login", json=payload)
        # Should return 400 or 422
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_auth_logout():
    """Test POST /api/auth/logout."""
    async with app_server() as server:
        response = await server.post("/api/auth/logout")
        # Should succeed or return 401 if not authenticated
        assert response.status_code in [200, 401]


@pytest.mark.integration
async def test_auth_status_structure():
    """Test auth status response structure."""
    async with app_server() as server:
        response = await server.get("/api/auth/status")
        assert response.status_code == 200
        data = response.json()
        # Should have some auth-related fields
        assert isinstance(data, dict)
        assert len(data) > 0
