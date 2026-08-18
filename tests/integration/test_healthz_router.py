# -*- coding: utf-8 -*-
"""Integration tests for Health Check API endpoints.

Tests cover:
- GET /api/healthz: health check
- GET /api/healthz/ready: readiness check
- GET /api/healthz/live: liveness check
"""

import pytest

from conftest import app_server


@pytest.mark.integration
async def test_healthz():
    """Test GET /api/healthz returns health status."""
    async with app_server() as server:
        response = await server.get("/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data or "healthy" in data


@pytest.mark.integration
async def test_healthz_ready():
    """Test GET /api/healthz/ready returns readiness status."""
    async with app_server() as server:
        response = await server.get("/api/healthz/ready")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_healthz_live():
    """Test GET /api/healthz/live returns liveness status."""
    async with app_server() as server:
        response = await server.get("/api/healthz/live")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_healthz_structure():
    """Test health check response structure."""
    async with app_server() as server:
        response = await server.get("/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have status-related fields
        assert len(data) > 0


@pytest.mark.integration
async def test_healthz_ready_structure():
    """Test readiness check response structure."""
    async with app_server() as server:
        response = await server.get("/api/healthz/ready")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
