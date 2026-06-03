# -*- coding: utf-8 -*-
"""Integration tests for the public frontend-plugin router.

These endpoints intentionally bypass authentication so an unauthenticated
login page can fetch the plugin list and load plugin bundles.
"""
from __future__ import annotations

import pytest

_FRONTEND_PLUGIN_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p1
def test_frontend_plugin_list_returns_array_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/frontend_plugin returns a JSON array of installed
      plugins with frontend metadata. This endpoint is unauthenticated
      (used by the login page to load custom plugin bundles before the
      user has authenticated), so a regression breaks the login
      experience for users with frontend plugins.

    Test flow:
    1. GET /api/frontend_plugin.
    2. Assert 200 and the body is a list (may be empty in clean env).
    3. If non-empty, assert each item exposes id and name as strings.

    API endpoints:
    - GET /api/frontend_plugin
    """
    resp = app_server.api_request(
        "GET",
        "/api/frontend_plugin",
        timeout=_FRONTEND_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)
    for item in payload:
        assert isinstance(item.get("id"), str) and item["id"]
        assert isinstance(item.get("name"), str) and item["name"]


@pytest.mark.integration
@pytest.mark.p2
def test_frontend_plugin_file_for_missing_plugin_returns_404(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/frontend_plugin/{plugin_id}/files/{path} returns
      404 when the plugin is not installed. Path-traversal protection
      lives in the underlying serve_plugin_ui_file helper.

    Test flow:
    1. GET /api/frontend_plugin/<unknown-plugin>/files/main.js.
    2. Assert 404 status.

    API endpoints:
    - GET /api/frontend_plugin/{plugin_id}/files/{file_path:path}
    """
    resp = app_server.api_request(
        "GET",
        "/api/frontend_plugin/integ-unknown-plugin/files/main.js",
        timeout=_FRONTEND_PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
