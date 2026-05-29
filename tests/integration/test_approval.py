# -*- coding: utf-8 -*-
"""Integration tests for tool-guard approval APIs."""
from __future__ import annotations

import pytest

_APPROVAL_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p0
def test_approval_approve_returns_404_for_missing_request(app_server) -> None:
    """Test purpose:
    - Verify POST /api/approval/approve returns 404 when the referenced
      approval request_id does not exist in the approval service.

    Test flow:
    1. POST /api/approval/approve with a synthetic request_id + session_id.
    2. Assert 404 response with ``detail`` containing
       ``Approval request not found``.

    API endpoints:
    - POST /api/approval/approve
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/approve",
        json={
            "request_id": "integ-missing-request-id-0001",
            "session_id": "integ-session-approve-404",
        },
        timeout=_APPROVAL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert "Approval request not found" in detail


@pytest.mark.integration
@pytest.mark.p2
def test_approval_deny_returns_404_for_missing_request(app_server) -> None:
    """Test purpose:
    - Verify POST /api/approval/deny returns 404 when the referenced
      approval request_id does not exist (mirror of the approve path).

    Test flow:
    1. POST /api/approval/deny with a synthetic request_id + session_id +
       reason.
    2. Assert 404 response with ``detail`` containing
       ``Approval request not found``.

    API endpoints:
    - POST /api/approval/deny
    """
    resp = app_server.api_request(
        "POST",
        "/api/approval/deny",
        json={
            "request_id": "integ-missing-request-id-0002",
            "session_id": "integ-session-deny-404",
            "reason": "integration deny test",
        },
        timeout=_APPROVAL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert "Approval request not found" in detail


@pytest.mark.integration
@pytest.mark.p2
def test_approval_list_returns_empty_by_default(app_server) -> None:
    """Test purpose:
    - Verify GET /api/approval/list returns an empty pending_approvals list
      and count=0 when no tool calls are awaiting approval.

    Test flow:
    1. GET /api/approval/list without session_id filter.
    2. Assert 200 with ``count`` == 0 and ``pending_approvals`` == [].

    API endpoints:
    - GET /api/approval/list
    """
    resp = app_server.api_request(
        "GET",
        "/api/approval/list",
        timeout=_APPROVAL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert payload.get("count") == 0
    assert payload.get("pending_approvals") == []


@pytest.mark.integration
@pytest.mark.p1
def test_approval_list_filters_by_session_id(app_server) -> None:
    """Test purpose:
    - Verify GET /api/approval/list with a ``session_id`` query parameter
      exercises the cross-session filter path
      (``get_pending_by_root_session``) and still returns the empty
      contract on a clean app. Console's approval drawer hits this path.

    Test flow:
    1. GET /api/approval/list with a synthetic session_id query parameter.
    2. Assert 200 with ``count`` == 0 and ``pending_approvals`` == [].

    API endpoints:
    - GET /api/approval/list
    """
    resp = app_server.api_request(
        "GET",
        "/api/approval/list",
        params={"session_id": "integ-approval-list-filter-session"},
        timeout=_APPROVAL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert payload.get("count") == 0
    assert payload.get("pending_approvals") == []
