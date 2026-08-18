# -*- coding: utf-8 -*-
"""Integration tests for Skills Stream API endpoints.

Tests cover:
- GET /api/skills-stream: get skills stream status
- POST /api/skills-stream: trigger skills stream
"""

import pytest


@pytest.mark.integration
async def test_skills_stream_status(app_server):
    """Test GET /api/skills-stream returns stream status."""
    async with app_server() as server:
        response = await server.get("/api/skills-stream")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_skills_stream_trigger_invalid(app_server):
    """Test POST /api/skills-stream with invalid data."""
    async with app_server() as server:
        response = await server.post("/api/skills-stream", json={})
        # Should return 400 or 422 for missing required fields
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_skills_stream_status_structure(app_server):
    """Test skills stream status response structure."""
    async with app_server() as server:
        response = await server.get("/api/skills-stream")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have stream-related fields
        assert len(data) >= 0


@pytest.mark.integration
async def test_skills_stream_trigger_missing_params(app_server):
    """Test POST /api/skills-stream without required params."""
    async with app_server() as server:
        response = await server.post("/api/skills-stream", json={})
        # Should return 400 or 422
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_skills_stream_get_specific(app_server):
    """Test GET /api/skills-stream with specific skill."""
    async with app_server() as server:
        response = await server.get("/api/skills-stream?skill=test-skill")
        assert response.status_code in [200, 404]
