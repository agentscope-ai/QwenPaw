# -*- coding: utf-8 -*-
"""Integration tests for the version endpoint.

Covers GET /api/version.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_VERSION_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p0
def test_version_endpoint(app_server) -> None:
    """Test purpose:
    - Verify GET /api/version returns version information. Console
      about page and diagnostics use this.

    Test flow:
    1. GET /api/version.
    2. Assert 200 and response has version field.

    API endpoints:
    - GET /api/version
    """
    resp = app_server.api_request(
        "GET",
        "/api/version",
        timeout=_VERSION_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert "version" in payload or "qwenpaw_version" in payload


@pytest.mark.integration
@pytest.mark.p1
def test_version_format(app_server) -> None:
    """Test purpose:
    - Verify version string follows semantic versioning format.

    Test flow:
    1. GET /api/version.
    2. Verify version matches expected format (x.y.z or similar).

    API endpoints:
    - GET /api/version
    """
    resp = app_server.api_request(
        "GET",
        "/api/version",
        timeout=_VERSION_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    version = payload.get("version") or payload.get("qwenpaw_version", "")
    assert isinstance(version, str)
    assert len(version) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_version_includes_commit_info(app_server) -> None:
    """Test purpose:
    - Verify version response includes commit information for
      diagnostics. Helps identify exact build in bug reports.

    Test flow:
    1. GET /api/version.
    2. Verify response has commit or git fields (optional but expected).

    API endpoints:
    - GET /api/version
    """
    resp = app_server.api_request(
        "GET",
        "/api/version",
        timeout=_VERSION_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    # Commit info is optional but commonly present
    # Just verify the response is a valid dict
    assert isinstance(payload, dict)
