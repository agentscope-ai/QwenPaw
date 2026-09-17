# -*- coding: utf-8 -*-
"""Integration tests for Skills API endpoints.

Tests cover:
- GET /api/skills: list available skills
- GET /api/skills/{skill_id}: get skill details
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_skills_list(app_server) -> None:
    """Test GET /api/skills returns skill list."""
    response = app_server.api_request("GET", "/api/skills")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should have at least some skills
    if len(data) > 0:
        skill = data[0]
        assert "id" in skill or "name" in skill


@pytest.mark.integration
@pytest.mark.p1
def test_skills_list_with_filters(app_server) -> None:
    """Test GET /api/skills with query parameters."""
    # Test with limit parameter
    response = app_server.api_request("GET", "/api/skills?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.p1
def test_skills_get_nonexistent(app_server) -> None:
    """Test GET /api/skills/{skill_id} with non-existent skill."""
    response = app_server.api_request(
        "GET",
        "/api/skills/nonexistent-skill-id-12345",
    )
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_skills_empty_filter(app_server) -> None:
    """Test GET /api/skills with empty filter."""
    response = app_server.api_request("GET", "/api/skills?category=")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_skills_pagination(app_server) -> None:
    """Test skills list pagination."""
    # Get first page
    response1 = app_server.api_request("GET", "/api/skills?limit=2&offset=0")
    assert response1.status_code == 200

    # Get second page
    response2 = app_server.api_request("GET", "/api/skills?limit=2&offset=2")
    assert response2.status_code == 200

    # Results should be different (if enough skills exist)
    data1 = response1.json()
    data2 = response2.json()
    if len(data1) == 2 and len(data2) > 0:
        # Should not have duplicate skills
        ids1 = {s.get("id") or s.get("name") for s in data1}
        ids2 = {s.get("id") or s.get("name") for s in data2}
        assert len(ids1 & ids2) == 0
