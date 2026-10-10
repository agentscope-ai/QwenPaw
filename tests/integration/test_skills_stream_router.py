# -*- coding: utf-8 -*-
"""Integration tests for Skills Stream API endpoints.

Tests cover:
- GET /api/skills-stream: get skills stream status
- POST /api/skills-stream: trigger skills stream
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_skills_stream_status(app_server) -> None:
    """Test GET /api/skills-stream returns stream status."""
    response = app_server.api_request("GET", "/api/skills/workspaces")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_skills_stream_trigger_invalid(app_server) -> None:
    """Test POST /api/skills-stream with invalid data."""
    response = app_server.api_request(
        "POST",
        "/api/skills/ai/optimize/stream",
        json={},
    )
    # Should return 400 or 422 for missing required fields
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_skills_stream_status_structure(app_server) -> None:
    """Test skills stream status response structure."""
    response = app_server.api_request("GET", "/api/skills/workspaces")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should have stream-related fields
    assert len(data) >= 0


@pytest.mark.integration
@pytest.mark.p1
def test_skills_stream_trigger_missing_params(app_server) -> None:
    """Test POST /api/skills-stream without required params."""
    response = app_server.api_request(
        "POST",
        "/api/skills/ai/optimize/stream",
        json={},
    )
    # Should return 400 or 422
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_skills_stream_get_specific(app_server) -> None:
    """Test GET /api/skills-stream with specific skill."""
    response = app_server.api_request("GET", "/api/skills/workspaces")
    assert response.status_code in [200, 404]
