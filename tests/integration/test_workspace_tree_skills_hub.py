# -*- coding: utf-8 -*-
"""Integration tests for workspace tree / available-commands and the
skills hub install task surface.

Third coverage-sprint batch, targeted at uncovered lines reported by the
coverage digest (workspace.py tree walk + /commands/available, skills.py
hub install status/cancel error branches).

Tests cover:
- GET /api/workspace/tree: paged directory listing (project + workspace roots)
- GET /api/workspace/tree: invalid root / invalid cursor error paths
- GET /api/workspace/commands/available: slash command menu payload
- GET /api/skills/hub/install/status/{task_id}: unknown task 404
- POST /api/skills/hub/install/cancel/{task_id}: unknown task 404
- GET /api/skills/workspaces: skill workspaces list
- GET /api/skills/pool: skill pool list
- POST /api/skills/pool/refresh: pool refresh
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_TREE_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# workspace tree
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_tree_lists_children(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/tree returns a paged listing of the
      project root's immediate children.

    API endpoints:
    - GET /api/workspace/tree
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/tree",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "entries" in payload or "children" in payload or "items" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_tree_workspace_root(app_server) -> None:
    """Test purpose:
    - Verify the tree endpoint accepts root=workspace.

    API endpoints:
    - GET /api/workspace/tree
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/tree",
        params={"root": "workspace"},
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_tree_invalid_root_rejected(app_server) -> None:
    """Test purpose:
    - Verify root values other than project/workspace are rejected.

    API endpoints:
    - GET /api/workspace/tree
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/tree",
        params={"root": "bogus"},
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_tree_invalid_cursor_rejected(app_server) -> None:
    """Test purpose:
    - Verify a malformed cursor yields 400 (InvalidCursor branch).

    API endpoints:
    - GET /api/workspace/tree
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/tree",
        params={"cursor": "not-a-valid-cursor"},
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_tree_limit_bounds(app_server) -> None:
    """Test purpose:
    - Verify the limit query is validated (ge=1, le=MAX_PAGE_SIZE).

    API endpoints:
    - GET /api/workspace/tree
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/tree",
        params={"limit": "0"},
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


# ------------------------------------------------------------------ #
# available commands
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_commands_available(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/commands/available returns the slash
      command menu payload with name/description/category entries.

    API endpoints:
    - GET /api/workspace/commands/available
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/commands/available",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    commands = payload.get("commands")
    assert isinstance(commands, list)
    assert len(commands) > 0
    entry = commands[0]
    assert "name" in entry


# ------------------------------------------------------------------ #
# skills hub install task surface
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_skills_hub_install_status_unknown_task(app_server) -> None:
    """Test purpose:
    - Verify status polling for an unknown install task yields 404.

    API endpoints:
    - GET /api/skills/hub/install/status/{task_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/hub/install/status/integ-unknown-task",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_skills_hub_install_cancel_unknown_task(app_server) -> None:
    """Test purpose:
    - Verify cancelling an unknown install task yields 404.

    API endpoints:
    - POST /api/skills/hub/install/cancel/{task_id}
    """
    resp = app_server.api_request(
        "POST",
        "/api/skills/hub/install/cancel/integ-unknown-task",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ------------------------------------------------------------------ #
# skills pool builtin surface
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_skills_pool_builtin_sources(app_server) -> None:
    """Test purpose:
    - Verify GET /api/skills/pool/builtin-sources returns the builtin
      import candidate list.

    API endpoints:
    - GET /api/skills/pool/builtin-sources
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/pool/builtin-sources",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p1
def test_skills_pool_builtin_notice_structure(app_server) -> None:
    """Test purpose:
    - Verify GET /api/skills/pool/builtin-notice returns the update
      notice payload (fingerprint/has_updates/total_changes fields).

    API endpoints:
    - GET /api/skills/pool/builtin-notice
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/pool/builtin-notice",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "fingerprint" in payload
    assert "has_updates" in payload
    assert "total_changes" in payload


# ------------------------------------------------------------------ #
# skills workspaces + pool
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_skills_workspaces_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/skills/workspaces returns the list of skill
      workspaces.

    API endpoints:
    - GET /api/skills/workspaces
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/workspaces",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p1
def test_skills_pool_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/skills/pool returns the skill pool list.

    API endpoints:
    - GET /api/skills/pool
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/pool",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p1
def test_skills_pool_refresh(app_server) -> None:
    """Test purpose:
    - Verify POST /api/skills/pool/refresh triggers a pool refresh.

    API endpoints:
    - POST /api/skills/pool/refresh
    """
    resp = app_server.api_request(
        "POST",
        "/api/skills/pool/refresh",
        timeout=_TREE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
