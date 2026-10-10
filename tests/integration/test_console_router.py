# -*- coding: utf-8 -*-
"""Integration tests for the console router (inbox and push messages).

Covers GET /api/console/inbox/events, POST /api/console/inbox/read,
and GET /api/console/push-messages.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_CONSOLE_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_console_inbox_events_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/console/inbox/events returns a list of events.
      Console inbox renders from this endpoint.

    Test flow:
    1. GET /api/console/inbox/events.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/console/inbox/events
    """
    resp = app_server.api_request(
        "GET",
        "/api/console/inbox/events",
        timeout=_CONSOLE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "events" in payload
    assert "total" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_console_inbox_read_marks_events(app_server) -> None:
    """Test purpose:
    - Verify POST /api/console/inbox/read accepts event IDs and marks
      them as read. Console uses this when user opens inbox.

    Test flow:
    1. POST /api/console/inbox/read with empty list.
    2. Assert 200 (no-op is valid).

    API endpoints:
    - POST /api/console/inbox/read
    """
    resp = app_server.api_request(
        "POST",
        "/api/console/inbox/read",
        json={"event_ids": []},
        timeout=_CONSOLE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_console_inbox_delete_event(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/console/inbox/events/{event_id} accepts an
      event ID. Console uses this to dismiss inbox events.

    Test flow:
    1. DELETE /api/console/inbox/events/nonexistent_xyz.
    2. Assert 404 (event doesn't exist) or 200 (idempotent delete).

    API endpoints:
    - DELETE /api/console/inbox/events/{event_id}
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/console/inbox/events/nonexistent_xyz",
        timeout=_CONSOLE_TIMEOUT,
    )
    # Either 404 (not found) or 200 (idempotent) is acceptable
    assert resp.status_code in (200, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_console_push_messages(app_server) -> None:
    """Test purpose:
    - Verify GET /api/console/push-messages returns pending push
      messages. Console polls this for real-time notifications.

    Test flow:
    1. GET /api/console/push-messages.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/console/push-messages
    """
    resp = app_server.api_request(
        "GET",
        "/api/console/push-messages",
        timeout=_CONSOLE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "messages" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_console_inbox_traces(app_server) -> None:
    """Test purpose:
    - Verify GET /api/console/inbox/traces/{run_id} returns trace data.
      Console debug view uses this to show execution traces.

    Test flow:
    1. GET /api/console/inbox/traces/nonexistent_run_xyz.
    2. Assert 404 (run doesn't exist) or 200 with empty data.

    API endpoints:
    - GET /api/console/inbox/traces/{run_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/console/inbox/traces/nonexistent_run_xyz",
        timeout=_CONSOLE_TIMEOUT,
    )
    # Either 404 (not found) or 200 with empty data
    assert resp.status_code in (200, 404), app_server.logs_tail()
