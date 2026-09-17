# -*- coding: utf-8 -*-
"""Integration tests for workspace project-directory and git endpoints.

Fourth coverage-sprint batch, targeted at uncovered lines in
src/qwenpaw/app/routers/workspace.py (project-directory set/get,
git status/branches).

Tests cover:
- PUT /api/workspace/project-directory: set project directory
- GET /api/workspace/project-directory: get current project directory
- GET /api/workspace/git/status: git repository status
- GET /api/workspace/git/branches: list git branches
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_WS_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# project-directory
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_project_directory_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/project-directory returns the current
      project directory path.

    API endpoints:
    - GET /api/workspace/project-directory
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/project-directory",
        timeout=_WS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "path" in payload or "project_directory" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_project_directory_set_invalid(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/workspace/project-directory with an invalid path
      is rejected.

    API endpoints:
    - PUT /api/workspace/project-directory
    """
    resp = app_server.api_request(
        "PUT",
        "/api/workspace/project-directory",
        json={"path": "/no/such/path"},
        timeout=_WS_TIMEOUT,
    )
    assert resp.status_code in (400, 404, 422), app_server.logs_tail()


# ------------------------------------------------------------------ #
# git status
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_git_status(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/git/status returns the git repository
      status (branch, dirty, etc.).

    API endpoints:
    - GET /api/workspace/git/status
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/git/status",
        timeout=_WS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "branch" in payload or "dirty" in payload or "status" in payload


# ------------------------------------------------------------------ #
# git branches
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_git_branches(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/git/branches returns the list of git
      branches.

    API endpoints:
    - GET /api/workspace/git/branches
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/git/branches",
        timeout=_WS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)
