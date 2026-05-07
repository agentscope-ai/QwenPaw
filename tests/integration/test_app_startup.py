# -*- coding: utf-8 -*-
"""Integration smoke tests for app startup and console."""
from __future__ import annotations


def test_api_version_ok(app_server) -> None:
    """App should expose /api/version after startup."""
    response = app_server.api_request("GET", "/api/version")
    assert response.status_code == 200, app_server.logs_tail()
    payload = response.json()
    assert "version" in payload
    assert isinstance(payload["version"], str)
    assert payload["version"].strip()


def test_console_entry_or_fallback_ok(app_server) -> None:
    """Console path should return HTML or explicit unavailable fallback."""
    response = app_server.api_request("GET", "/console/")
    if response.status_code == 200:
        content_type = response.headers.get("content-type", "").lower()
        assert "text/html" in content_type
        body = response.text
        assert body.strip()
        assert "<!doctype html>" in body.lower() or "<html" in body.lower()
        return

    # Source installs without prebuilt frontend currently return 404 at
    # /console/. In this case, "/" should still expose a clear fallback
    # message instead of crashing.
    assert response.status_code == 404, app_server.logs_tail()
    root_response = app_server.api_request("GET", "/")
    assert root_response.status_code == 200, app_server.logs_tail()
    fallback = root_response.json()
    assert "message" in fallback
    assert "web console is not available" in fallback["message"]
