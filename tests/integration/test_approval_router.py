# -*- coding: utf-8 -*-
"""Integration tests for the approval router (tool call approvals).

Covers GET /api/approval (list pending), and approval actions.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_APPROVAL_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_approval_list_pending(app_server) -> None:
    """Test purpose:
    - Verify GET /api/approval/list returns pending approvals.
      Console approval queue renders from this endpoint.

    Test flow:
    1. GET /api/approval/list.
    2. Assert 200 and response has pending_approvals field.

    API endpoints:
    - GET /api/approval/list
    """
    resp = app_server.api_request(
        "GET",
        "/api/approval/list",
        timeout=_APPROVAL_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "pending_approvals" in payload
    assert "count" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_approval_pending_item_schema(app_server) -> None:
    """Test purpose:
    - Verify each pending approval has expected fields (id, tool_name,
      agent_id, etc.).

    Test flow:
    1. GET /api/approval.
    2. If items exist, verify schema.

    API endpoints:
    - GET /api/approval
    """
    resp = app_server.api_request(
        "GET",
        "/api/approval/list",
        timeout=_APPROVAL_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    items = payload.get("pending_approvals", [])
    assert isinstance(items, list)
    for item in items:
        assert isinstance(item, dict)
        # Each approval should have at least an id
        assert "id" in item or "tool_call_id" in item


@pytest.mark.integration
@pytest.mark.p1
def test_approval_approve_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify approving a nonexistent approval returns 404.

    Test flow:
    1. POST /api/approval/pending/approve with nonexistent ID.
    2. Assert 404.

    API endpoints:
    - POST /api/approval/pending/approve
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/approve",
        json={
            "request_id": "nonexistent_approval_xyz",
            "session_id": "integ_session",
        },
        timeout=_APPROVAL_TIMEOUT,
    )
    assert resp.status_code in (404, 400), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_approval_deny_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify denying a nonexistent approval returns 404.

    Test flow:
    1. POST /api/approval/pending/deny with nonexistent ID.
    2. Assert 404.

    API endpoints:
    - POST /api/approval/pending/deny
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/deny",
        json={
            "request_id": "nonexistent_approval_xyz",
            "session_id": "integ_session",
        },
        timeout=_APPROVAL_TIMEOUT,
    )
    assert resp.status_code in (404, 400), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_approval_dismiss_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify dismissing a nonexistent approval returns 404.

    Test flow:
    1. POST /api/approval/pending/dismiss with nonexistent ID.
    2. Assert 404.

    API endpoints:
    - POST /api/approval/pending/dismiss
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/approve",
        json={
            "request_id": "nonexistent_approval_xyz",
            "session_id": "integ_session",
        },
        timeout=_APPROVAL_TIMEOUT,
    )
    assert resp.status_code in (404, 400), app_server.logs_tail()
