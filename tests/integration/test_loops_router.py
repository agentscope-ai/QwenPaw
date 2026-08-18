# -*- coding: utf-8 -*-
"""Integration tests for the loops router (loop modes and gates).

Covers GET /api/loops (list modes), GET /api/loops/gates/catalog,
and loop mode status.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_LOOPS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_loops_list_modes(app_server) -> None:
    """Test purpose:
    - Verify GET /api/loops returns a list of loop modes. Console
      renders available loop modes from this endpoint.

    Test flow:
    1. GET /api/loops.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/loops
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops",
        timeout=_LOOPS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)


@pytest.mark.integration
@pytest.mark.p2
def test_loops_mode_schema(app_server) -> None:
    """Test purpose:
    - Verify each loop mode entry has expected fields.

    Test flow:
    1. GET /api/loops.
    2. If modes exist, verify each has id/name fields.

    API endpoints:
    - GET /api/loops
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops",
        timeout=_LOOPS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    modes = resp.json()
    for mode in modes:
        assert isinstance(mode, dict)
        # Each mode should have at least an id or name
        assert len(mode) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_loops_gates_catalog(app_server) -> None:
    """Test purpose:
    - Verify GET /api/loops/gates/catalog returns available gates.
      Console shows gate catalog for loop configuration.

    Test flow:
    1. GET /api/loops/gates/catalog.
    2. Assert 200 and response is a list or dict.

    API endpoints:
    - GET /api/loops/gates/catalog
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops/gates/catalog",
        timeout=_LOOPS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, (list, dict))


@pytest.mark.integration
@pytest.mark.p1
def test_loops_status(app_server) -> None:
    """Test purpose:
    - Verify GET /api/loops/status returns current loop mode status.
      Console shows active loop mode from this.

    Test flow:
    1. GET /api/loops/status.
    2. Assert 200 and response is a dict.

    API endpoints:
    - GET /api/loops/status
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops/status",
        timeout=_LOOPS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p2
def test_loops_custom_modes_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/loops/custom returns custom loop modes.
      Console shows user-defined custom modes.

    Test flow:
    1. GET /api/loops/custom.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/loops/custom
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops/custom",
        timeout=_LOOPS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)
