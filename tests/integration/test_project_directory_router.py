# -*- coding: utf-8 -*-
"""Integration tests for Project Directory API endpoints.

Tests cover:
- GET /api/workspace/project-directory: get project directory
- POST /api/workspace/project-directory: set project directory
"""

import pytest



@pytest.mark.integration
async def test_project_directory_get(app_server):
    """Test GET /api/workspace/project-directory returns directory info."""
    async with app_server() as server:
        response = await server.get("/api/workspace/project-directory")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_project_directory_set_invalid(app_server):
    """Test POST /api/workspace/project-directory with invalid path."""
    async with app_server() as server:
        response = await server.post(
            "/api/workspace/project-directory",
            json={"path": "/no/such/path"},
        )
        # Should return 400 or 404 for invalid path
        assert response.status_code in [400, 404]


@pytest.mark.integration
async def test_project_directory_set_missing_path(app_server):
    """Test POST /api/workspace/project-directory without path."""
    async with app_server() as server:
        url = "/api/workspace/project-directory"
        response = await server.post(url, json={})
        # Should return 400 or 422
        assert response.status_code in [400, 422]


@pytest.mark.integration
async def test_project_directory_get_structure(app_server):
    """Test project directory response structure."""
    async with app_server() as server:
        response = await server.get("/api/workspace/project-directory")
        assert response.status_code == 200
        data = response.json()
        # Should have path-related fields
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_project_directory_set_relative_path(app_server):
    """Test POST /api/workspace/project-directory with relative path."""
    async with app_server() as server:
        response = await server.post(
            "/api/workspace/project-directory",
            json={"path": "./rel"},
        )
        # Should handle relative paths appropriately
        assert response.status_code in [200, 400]
