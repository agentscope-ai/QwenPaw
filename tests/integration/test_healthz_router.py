# -*- coding: utf-8 -*-
"""Integration tests for Health Check API endpoints.

Tests cover:
- GET /api/healthz: health check
- GET /api/healthz/ready: readiness check
- GET /api/healthz/live: liveness check
"""

import pytest



@pytest.mark.integration
async def test_healthz(app_server):
    """Test GET /api/healthz returns health status."""
    async with app_server() as server:
        response = await server.get("/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data or "healthy" in data


@pytest.mark.integration
async def test_healthz_ready(app_server):
    """Test GET /api/healthz/ready returns readiness status."""
    async with app_server() as server:
        response = await server.get("/api/healthz/ready")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_healthz_live(app_server):
    """Test GET /api/healthz/live returns liveness status."""
    async with app_server() as server:
        response = await server.get("/api/healthz/live")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_healthz_structure(app_server):
    """Test health check response structure."""
    async with app_server() as server:
        response = await server.get("/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have status-related fields
        assert len(data) > 0


@pytest.mark.integration
async def test_healthz_ready_structure(app_server):
    """Test readiness check response structure."""
    async with app_server() as server:
        response = await server.get("/api/healthz/ready")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
