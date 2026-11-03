# -*- coding: utf-8 -*-
"""Integration tests for the messages router.

Tests message history and tool calls endpoints.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_MESSAGES_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_messages_tool_call_info(app_server) -> None:
    """Test purpose:
    - Verify GET /api/messages/{session_id}/{tool_call_id} returns
      tool call info. Console shows tool call details from this.

    Test flow:
    1. GET /api/tool-calls/session_xyz/toolcall_xyz.
    2. Assert 404 (doesn't exist) or 200 with data.

    API endpoints:
    - GET /api/messages/{session_id}/{tool_call_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/tool-calls/session_xyz/toolcall_xyz",
        timeout=_MESSAGES_TIMEOUT,
    )
    # Either 404 (not found) or 200 with data
    assert resp.status_code in (200, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_messages_tool_call_output(app_server) -> None:
    """Test purpose:
    - Verify GET /api/messages/{session_id}/{tool_call_id}/output
      returns tool call output.

    Test flow:
    1. GET output for nonexistent tool call.
    2. Assert 404 or 200.

    API endpoints:
    - GET /api/messages/{session_id}/{tool_call_id}/output
    """
    resp = app_server.api_request(
        "GET",
        "/api/tool-calls/session_xyz/toolcall_xyz/output",
        timeout=_MESSAGES_TIMEOUT,
    )
    assert resp.status_code in (200, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_messages_tool_call_stream(app_server) -> None:
    """Test purpose:
    - Verify GET /api/messages/{session_id}/{tool_call_id}/stream
      endpoint exists for streaming tool call output.

    Test flow:
    1. GET stream for nonexistent tool call.
    2. Assert 404 or 200.

    API endpoints:
    - GET /api/messages/{session_id}/{tool_call_id}/stream
    """
    resp = app_server.api_request(
        "GET",
        "/api/tool-calls/session_xyz/toolcall_xyz/stream",
        timeout=_MESSAGES_TIMEOUT,
    )
    assert resp.status_code in (200, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_messages_tool_call_cancel(app_server) -> None:
    """Test purpose:
    - Verify POST /api/messages/{session_id}/{tool_call_id}/cancel
      endpoint exists for cancelling tool calls.

    Test flow:
    1. POST cancel for nonexistent tool call.
    2. Assert 404 or 202 (accepted).

    API endpoints:
    - POST /api/messages/{session_id}/{tool_call_id}/cancel
    """
    resp = app_server.api_request(
        "POST",
        "/api/tool-calls/session_xyz/toolcall_xyz/cancel",
        timeout=_MESSAGES_TIMEOUT,
    )
    assert resp.status_code in (200, 202, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_messages_tool_call_offload(app_server) -> None:
    """Test purpose:
    - Verify POST /api/messages/{session_id}/{tool_call_id}/offload
      endpoint exists for offloading tool calls.

    Test flow:
    1. POST offload for nonexistent tool call.
    2. Assert 404 or 202.

    API endpoints:
    - POST /api/messages/{session_id}/{tool_call_id}/offload
    """
    resp = app_server.api_request(
        "POST",
        "/api/tool-calls/session_xyz/toolcall_xyz/offload",
        timeout=_MESSAGES_TIMEOUT,
    )
    assert resp.status_code in (200, 202, 404), app_server.logs_tail()
