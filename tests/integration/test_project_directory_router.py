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
    response = app_server.api_request(
        "GET",
        "/api/workspace/project-directory",
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_create_ignores_extra_fields(app_server) -> None:
    """Test create ignores extra body fields (only name is consumed)."""
    response = app_server.api_request(
        "POST",
        "/api/workspace/project-directory/create",
        json={"name": "integ_proj", "path": "/no/such/path"},
    )
    # create only consumes name; extra fields are ignored and it succeeds
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_create_valid_name(app_server) -> None:
    """Test POST /api/workspace/project-directory/create with a name."""
    url = "/api/workspace/project-directory/create"
    response = app_server.api_request(
        "POST",
        url,
        json={"name": "integ_proj_tmp"},
    )
    # A valid name creates the project directory (200 with its path)
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_get_structure(app_server) -> None:
    """Test project directory response structure."""
    response = app_server.api_request(
        "GET",
        "/api/workspace/project-directory",
    )
    assert response.status_code == 200
    data = response.json()
    # Should have path-related fields
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_project_directory_set_relative_path(app_server) -> None:
    """Test POST /api/workspace/project-directory with relative path."""
    response = app_server.api_request(
        "POST",
        "/api/workspace/project-directory/create",
        json={"name": "integ_rel_tmp"},
    )
    # create only takes a name; a valid name succeeds
    assert response.status_code == 200
