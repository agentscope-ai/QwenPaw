# -*- coding: utf-8 -*-
"""Integration tests for Providers API endpoints.

Tests cover:
- GET /api/providers: list providers
- GET /api/providers/{provider_id}: get provider details
- POST /api/providers: add provider
"""
import pytest

from .conftest import app_server


@pytest.mark.integration
async def test_providers_list():
    """Test GET /api/providers returns provider list."""
    async with app_server() as server:
        response = await server.get("/api/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_providers_get_nonexistent():
    """Test GET /api/providers/{provider_id} with non-existent provider."""
    async with app_server() as server:
        response = await server.get("/api/providers/nonexistent-provider-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_providers_add_invalid():
    """Test POST /api/providers with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/providers", json={})
        # Should return 400 or 422 for missing required fields
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_providers_list_with_filter():
    """Test GET /api/providers with filter."""
    async with app_server() as server:
        response = await server.get("/api/providers?type=")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_providers_list_pagination():
    """Test providers list pagination."""
    async with app_server() as server:
        response = await server.get("/api/providers?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_providers_structure():
    """Test provider response structure."""
    async with app_server() as server:
        response = await server.get("/api/providers")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            provider = data[0]
            assert isinstance(provider, dict)
            # Should have id or name field
            assert "id" in provider or "name" in provider
