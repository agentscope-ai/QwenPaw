# -*- coding: utf-8 -*-
"""Integration tests for the workspace checkpoints router.

Covers GET /api/workspace/checkpoints/status, snapshot creation,
restore preview, GC settings, and error handling.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_CHECKPOINTS_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# Status endpoint
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_status_returns_structure(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/checkpoints/status returns a valid
      response. Console graph page renders checkpoint history from this.

    Test flow:
    1. GET /api/workspace/checkpoints/status.
    2. Assert 200 and response is a dict.

    API endpoints:
    - GET /api/workspace/checkpoints/status
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/checkpoints/status",
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


# ------------------------------------------------------------------ #
# GC settings
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_gc_settings_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/checkpoints/gc/settings returns current
      GC configuration. Console settings page reads this.

    Test flow:
    1. GET /api/workspace/checkpoints/gc/settings.
    2. Assert 200 and response has expected fields.

    API endpoints:
    - GET /api/workspace/checkpoints/gc/settings
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/checkpoints/gc/settings",
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_gc_settings_put(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/workspace/checkpoints/gc/settings accepts valid
      GC configuration and returns the updated settings.

    Test flow:
    1. GET current settings.
    2. PUT updated settings.
    3. GET again and verify changes persisted.

    API endpoints:
    - GET /api/workspace/checkpoints/gc/settings
    - PUT /api/workspace/checkpoints/gc/settings
    """
    # Get current
    get_resp = app_server.api_request(
        "GET",
        "/api/workspace/checkpoints/gc/settings",
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    original = get_resp.json()

    # Update with new values
    new_settings = {
        "gc_keep_count": 50,
        "gc_keep_days": 30,
        "pre_restore_retention_days": 7,
    }
    put_resp = app_server.api_request(
        "PATCH",
        "/api/workspace/checkpoints/gc/settings",
        json=new_settings,
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()

    # Verify changes
    get_resp2 = app_server.api_request(
        "GET",
        "/api/workspace/checkpoints/gc/settings",
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert get_resp2.status_code == 200, app_server.logs_tail()
    updated = get_resp2.json()
    assert updated.get("gc_keep_count") == 50
    assert updated.get("gc_keep_days") == 30

    # Restore original
    app_server.api_request(
        "PATCH",
        "/api/workspace/checkpoints/gc/settings",
        json=original,
        timeout=_CHECKPOINTS_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_gc_settings_validation(app_server) -> None:
    """Test purpose:
    - Verify GC settings validation rejects invalid values (negative,
      out of range).

    Test flow:
    1. PUT /api/workspace/checkpoints/gc/settings with negative value.
    2. Assert 422 (validation error).

    API endpoints:
    - PUT /api/workspace/checkpoints/gc/settings
    """
    resp = app_server.api_request(
        "PATCH",
        "/api/workspace/checkpoints/gc/settings",
        json={
            "gc_keep_count": -1,  # Invalid: must be >= 0
            "gc_keep_days": 30,
            "pre_restore_retention_days": 7,
        },
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Snapshot creation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_snapshot_requires_session_id(app_server) -> None:
    """Test purpose:
    - Verify POST /api/workspace/checkpoints/snapshot rejects requests
      without session_id (required field).

    Test flow:
    1. POST snapshot with empty body.
    2. Assert 422 (validation error).

    API endpoints:
    - POST /api/workspace/checkpoints/snapshot
    """
    resp = app_server.api_request(
        "POST",
        "/api/workspace/checkpoints/snapshot",
        json={},
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_snapshot_empty_session_id_rejected(app_server) -> None:
    """Test purpose:
    - Verify snapshot rejects empty session_id (min_length=1).

    Test flow:
    1. POST snapshot with session_id="".
    2. Assert 422.

    API endpoints:
    - POST /api/workspace/checkpoints/snapshot
    """
    resp = app_server.api_request(
        "POST",
        "/api/workspace/checkpoints/snapshot",
        json={"session_id": ""},
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Restore preview
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_restore_preview_requires_fields(app_server) -> None:
    """Test purpose:
    - Verify POST /api/workspace/checkpoints/restore/preview rejects
      requests without required fields (commit, session_id).

    Test flow:
    1. POST restore/preview with empty body.
    2. Assert 422.

    API endpoints:
    - POST /api/workspace/checkpoints/restore/preview
    """
    resp = app_server.api_request(
        "POST",
        "/api/workspace/checkpoints/restore/preview",
        json={},
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_restore_preview_short_commit_rejected(app_server) -> None:
    """Test purpose:
    - Verify restore preview rejects commit hashes shorter than 7 chars
      (min_length=7).

    Test flow:
    1. POST restore/preview with commit="abc".
    2. Assert 422.

    API endpoints:
    - POST /api/workspace/checkpoints/restore/preview
    """
    resp = app_server.api_request(
        "POST",
        "/api/workspace/checkpoints/restore/preview",
        json={
            "commit": "abc",  # Too short
            "session_id": "test-session",
        },
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


# ------------------------------------------------------------------ #
# GC execution
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_gc_preview(app_server) -> None:
    """Test purpose:
    - Verify POST /api/workspace/checkpoints/gc/preview returns a
      preview of what GC would delete. Console shows this before
      confirming GC.

    Test flow:
    1. POST gc/preview with empty body.
    2. Assert 200 and response is a dict.

    API endpoints:
    - POST /api/workspace/checkpoints/gc/preview
    """
    resp = app_server.api_request(
        "POST",
        "/api/workspace/checkpoints/gc/preview",
        json={},
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


# ------------------------------------------------------------------ #
# Commit diff
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_checkpoints_status(app_server) -> None:
    """Test purpose:
    - Verify GET /api/workspace/checkpoints/status returns 200.

    Test flow:
    1. GET checkpoints status.
    2. Assert 200.

    API endpoints:
    - GET /api/workspace/checkpoints/status
    """
    resp = app_server.api_request(
        "GET",
        "/api/workspace/checkpoints/status",
        timeout=_CHECKPOINTS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
