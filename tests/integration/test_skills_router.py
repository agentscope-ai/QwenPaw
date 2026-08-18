# -*- coding: utf-8 -*-
"""Integration tests for Skills API endpoints.

Tests cover:
- GET /api/skills: list available skills
- GET /api/skills/{skill_id}: get skill details
"""
import pytest

from .conftest import app_server


@pytest.mark.integration
async def test_skills_list():
    """Test GET /api/skills returns skill list."""
    async with app_server() as server:
        response = await server.get("/api/skills")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least some skills
        if len(data) > 0:
            skill = data[0]
            assert "id" in skill or "name" in skill


@pytest.mark.integration
async def test_skills_list_with_filters():
    """Test GET /api/skills with query parameters."""
    async with app_server() as server:
        # Test with limit parameter
        response = await server.get("/api/skills?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_skills_get_nonexistent():
    """Test GET /api/skills/{skill_id} with non-existent skill."""
    async with app_server() as server:
        response = await server.get("/api/skills/nonexistent-skill-id-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_skills_empty_filter():
    """Test GET /api/skills with empty filter."""
    async with app_server() as server:
        response = await server.get("/api/skills?category=")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_skills_pagination():
    """Test skills list pagination."""
    async with app_server() as server:
        # Get first page
        response1 = await server.get("/api/skills?limit=2&offset=0")
        assert response.status_code == 200
        
        # Get second page
        response2 = await server.get("/api/skills?limit=2&offset=2")
        assert response.status_code == 200
        
        # Results should be different (if enough skills exist)
        data1 = response1.json()
        data2 = response2.json()
        if len(data1) == 2 and len(data2) > 0:
            # Should not have duplicate skills
            ids1 = {s.get("id") or s.get("name") for s in data1}
            ids2 = {s.get("id") or s.get("name") for s in data2}
            assert len(ids1 & ids2) == 0
