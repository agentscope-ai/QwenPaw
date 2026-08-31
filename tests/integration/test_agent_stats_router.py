# -*- coding: utf-8 -*-
"""Integration tests for the agent-stats router.

Covers GET /api/agent-stats with various date range parameters.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_STATS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_stats_summary_default_range(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agent-stats with no parameters returns a valid
      summary for the default 30-day range. Console dashboard renders
      this on load.

    Test flow:
    1. GET /api/agent-stats with no params.
    2. Assert 200 and response is a dict.

    API endpoints:
    - GET /api/agent-stats
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent-stats",
        timeout=_STATS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_stats_summary_with_date_range(app_server) -> None:
    """Test purpose:
    - Verify date range parameters are accepted.

    Test flow:
    1. GET /api/agent-stats with start_date and end_date.
    2. Assert 200.

    API endpoints:
    - GET /api/agent-stats
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent-stats",
        params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        timeout=_STATS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_agent_stats_summary_reversed_dates_swapped(app_server) -> None:
    """Test purpose:
    - Verify that reversed start/end dates are handled gracefully.

    Test flow:
    1. GET /api/agent-stats with start_date > end_date.
    2. Assert 200.

    API endpoints:
    - GET /api/agent-stats
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent-stats",
        params={
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        },
        timeout=_STATS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_agent_stats_summary_invalid_date_format(app_server) -> None:
    """Test purpose:
    - Verify invalid date format returns None (falls back to default).

    Test flow:
    1. GET /api/agent-stats with invalid date string.
    2. Assert 200.

    API endpoints:
    - GET /api/agent-stats
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent-stats",
        params={
            "start_date": "not-a-date",
        },
        timeout=_STATS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
