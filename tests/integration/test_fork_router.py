# -*- coding: utf-8 -*-
"""Integration tests for Fork API endpoints.

Tests cover:
- GET /api/fork: get fork status
- POST /api/fork: create fork
- GET /api/fork/list: list forks
"""

import pytest

from conftest import app_server


@pytest.mark.integration
async def test_fork_status():
    """Test GET /api/fork returns fork status."""
    async with app_server() as server:
        response = await server.get("/api/fork")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_fork_list():
    """Test GET /api/fork/list returns fork list."""
    async with app_server() as server:
        response = await server.get("/api/fork/list")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_fork_create_invalid():
    """Test POST /api/fork with invalid request."""
    async with app_server() as server:
        response = await server.post("/api/fork", json={})
        # Should return 400 or 422 for missing required fields
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_fork_list_pagination():
    """Test fork list pagination."""
    async with app_server() as server:
        response = await server.get("/api/fork/list?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_fork_list_empty_filter():
    """Test fork list with empty filter."""
    async with app_server() as server:
        response = await server.get("/api/fork/list?status=")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
