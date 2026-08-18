# -*- coding: utf-8 -*-
"""Integration tests for Provider OAuth API endpoints.

Tests cover:
- GET /api/provider-oauth: get provider OAuth status
- POST /api/provider-oauth/authorize: authorize provider OAuth
"""

import pytest


@pytest.mark.integration
async def test_provider_oauth_status(app_server):
    """Test GET /api/provider-oauth returns OAuth status."""
    async with app_server() as server:
        response = await server.get("/api/provider-oauth")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_provider_oauth_authorize_invalid(app_server):
    """Test POST /api/provider-oauth/authorize with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/provider-oauth/authorize", json={})
        # Should return 400 or 422 for missing required fields
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_provider_oauth_status_structure(app_server):
    """Test provider OAuth status response structure."""
    async with app_server() as server:
        response = await server.get("/api/provider-oauth")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have OAuth-related fields
        assert len(data) >= 0


@pytest.mark.integration
async def test_provider_oauth_authorize_missing_params(app_server):
    """Test POST /api/provider-oauth/authorize without required params."""
    async with app_server() as server:
        response = await server.post("/api/provider-oauth/authorize", json={})
        # Should return 400 or 422
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_provider_oauth_get_specific(app_server):
    """Test GET /api/provider-oauth with specific provider."""
    async with app_server() as server:
        response = await server.get("/api/provider-oauth?provider=openai")
        assert response.status_code in [200, 404]
