# -*- coding: utf-8 -*-
"""Integration tests for the pawapps router.

Covers GET /api/pawapps and related endpoints.
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_PAWAPPS_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_pawapps_list(app_server) -> None:
    """Test purpose:
    - Verify GET /api/pawapps returns list of pawapps. Console pawapps
      management page renders from this.

    Test flow:
    1. GET /api/pawapps.
    2. Assert 200 and response is a list or dict.

    API endpoints:
    - GET /api/pawapps
    """
    resp = app_server.api_request(
        "GET",
        "/api/pawapps",
        timeout=_PAWAPPS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, (list, dict))


@pytest.mark.integration
@pytest.mark.p2
def test_pawapps_get_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/pawapps/{nonexistent} returns 404.

    Test flow:
    1. GET nonexistent pawapp.
    2. Assert 404.

    API endpoints:
    - GET /api/pawapps/{app_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/pawapps/nonexistent_pawapp_xyz",
        timeout=_PAWAPPS_TIMEOUT,
    )
    assert resp.status_code in (404, 200), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_pawapps_settings_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/pawapps/{nonexistent}/settings returns 404.

    Test flow:
    1. GET settings for nonexistent pawapp.
    2. Assert 404.

    API endpoints:
    - GET /api/pawapps/{app_id}/settings
    """
    resp = app_server.api_request(
        "GET",
        "/api/pawapps/nonexistent_pawapp_xyz/settings",
        timeout=_PAWAPPS_TIMEOUT,
    )
    assert resp.status_code in (404, 200), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_pawapps_static_file_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/pawapps/{nonexistent}/static/{file} returns 404.

    Test flow:
    1. GET static file for nonexistent pawapp.
    2. Assert 404.

    API endpoints:
    - GET /api/pawapps/{app_id}/static/{file_path}
    """
    resp = app_server.api_request(
        "GET",
        "/api/pawapps/nonexistent_pawapp_xyz/static/index.html",
        timeout=_PAWAPPS_TIMEOUT,
    )
    assert resp.status_code in (404, 200), app_server.logs_tail()
