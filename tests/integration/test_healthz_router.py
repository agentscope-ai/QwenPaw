# -*- coding: utf-8 -*-
"""Integration tests for Health Check API endpoints.

Tests cover:
- GET /api/healthz: health check (the only healthz route upstream ships)
"""

import pytest
from helpers import default_http_timeout

_HEALTHZ_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_healthz(app_server) -> None:
    """Test purpose:
    - Verify GET /api/healthz returns 200 with a status payload once the
      app finished background startup.

    API endpoints:
    - GET /api/healthz
    """
    resp = app_server.api_request(
        "GET",
        "/api/healthz",
        timeout=_HEALTHZ_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert isinstance(data, dict)
    assert "status" in data


@pytest.mark.integration
@pytest.mark.p1
def test_healthz_structure(app_server) -> None:
    """Test purpose:
    - Verify the healthz payload carries status and agent/uptime fields.

    API endpoints:
    - GET /api/healthz
    """
    resp = app_server.api_request(
        "GET",
        "/api/healthz",
        timeout=_HEALTHZ_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    data = resp.json()
    assert data.get("status") == "ok"
    assert "agents_loaded" in data
    assert "uptime_seconds" in data
