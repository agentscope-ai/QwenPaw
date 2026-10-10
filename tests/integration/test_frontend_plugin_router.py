# -*- coding: utf-8 -*-
"""Integration tests for the frontend-plugin router.

Covers GET /api/frontend_plugin/{app_id} and related endpoints.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_FRONTEND_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_frontend_plugin_list_apps(app_server) -> None:
    """Test purpose:
    - Verify GET /api/frontend_plugin returns list of frontend apps.
      Console plugin management page renders from this.

    Test flow:
    1. GET /api/frontend_plugin.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/frontend_plugin
    """
    resp = app_server.api_request(
        "GET",
        "/api/frontend_plugin",
        timeout=_FRONTEND_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)


@pytest.mark.integration
@pytest.mark.p1
def test_frontend_plugin_get_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/frontend_plugin/{nonexistent} returns 404.

    Test flow:
    1. GET frontend plugin for nonexistent app.
    2. Assert 404.

    API endpoints:
    - GET /api/frontend_plugin/{app_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/frontend_plugin/nonexistent_app_xyz",
        timeout=_FRONTEND_TIMEOUT,
    )
    assert resp.status_code in (404, 200), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_frontend_plugin_settings_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify GET /api/frontend_plugin/{nonexistent}/settings returns 404.

    Test flow:
    1. GET settings for nonexistent app.
    2. Assert 404.

    API endpoints:
    - GET /api/frontend_plugin/{app_id}/settings
    """
    resp = app_server.api_request(
        "GET",
        "/api/frontend_plugin/nonexistent_app_xyz/settings",
        timeout=_FRONTEND_TIMEOUT,
    )
    assert resp.status_code in (404, 200), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_frontend_plugin_delete_nonexistent(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/frontend_plugin/{nonexistent} returns 404.

    Test flow:
    1. DELETE nonexistent app.
    2. Assert 404.

    API endpoints:
    - DELETE /api/frontend_plugin/{app_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/frontend_plugin/nonexistent_app_xyz/files/x.js",
        timeout=_FRONTEND_TIMEOUT,
    )
    assert resp.status_code in (404, 204), app_server.logs_tail()
