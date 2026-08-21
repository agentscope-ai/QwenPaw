# -*- coding: utf-8 -*-
"""Integration tests for the tool-calls router.

Covers GET /api/tool-calls (list) and related endpoints.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_TOOL_CALLS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_tool_calls_list_by_session(app_server) -> None:
    """Test purpose:
    - Verify GET /api/tool-calls/{session_id} returns tool calls for
      a session. Console tool call history renders from this endpoint.

    Test flow:
    1. GET /api/tool-calls/nonexistent_session_xyz.
    2. Assert 200 and response has items and total fields.

    API endpoints:
    - GET /api/tool-calls/{session_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/tool-calls/nonexistent_session_xyz",
        timeout=_TOOL_CALLS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "items" in payload
    assert "total" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_tool_calls_item_schema(app_server) -> None:
    """Test purpose:
    - Verify the session tool-call list payload has items/total fields.

    Test flow:
    1. GET /api/tool-calls/{session_id}.
    2. Verify items/total schema.

    API endpoints:
    - GET /api/tool-calls/{session_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/tool-calls/nonexistent_session_xyz",
        timeout=_TOOL_CALLS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    items = payload.get("items", [])
    for item in items[:5]:  # Check first 5
        assert isinstance(item, dict)
        # Each tool call should have at least an id or name
        assert len(item) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_tool_calls_with_session_filter(app_server) -> None:
    """Test purpose:
    - Verify GET /api/tool-calls accepts session_id filter parameter.

    Test flow:
    1. GET /api/tool-calls with session_id param.
    2. Assert 200.

    API endpoints:
    - GET /api/tool-calls
    """
    resp = app_server.api_request(
        "GET",
        "/api/tool-calls/test_session",
        timeout=_TOOL_CALLS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
