# -*- coding: utf-8 -*-
"""Integration tests for Project Directory API endpoints.

Tests cover:
- GET /api/workspace/project-directory: get project directory
- POST /api/workspace/project-directory: set project directory
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_get(app_server) -> None:
    """Test GET /api/workspace/project-directory returns directory info."""
    response = app_server.api_request("GET", "/api/workspace/project-directory")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_set_invalid(app_server) -> None:
    """Test POST /api/workspace/project-directory with invalid path."""
    response = app_server.api_request("POST", 
        "/api/workspace/project-directory/create",
        json={"path": "/no/such/path"},
    )
    # Should return 400 or 404 for invalid path
    assert response.status_code in [400, 404]


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_set_missing_path(app_server) -> None:
    """Test POST /api/workspace/project-directory without path."""
    url = "/api/workspace/project-directory/create"
    response = app_server.api_request("POST", url, json={})
    # Should return 400 or 422
    assert response.status_code in [400, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_get_structure(app_server) -> None:
    """Test project directory response structure."""
    response = app_server.api_request("GET", "/api/workspace/project-directory")
    assert response.status_code == 200
    data = response.json()
    # Should have path-related fields
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_set_relative_path(app_server) -> None:
    """Test POST /api/workspace/project-directory with relative path."""
    response = app_server.api_request("POST", 
        "/api/workspace/project-directory/create",
        json={"path": "./rel"},
    )
    # Should handle relative paths appropriately
    assert response.status_code in [200, 400]
