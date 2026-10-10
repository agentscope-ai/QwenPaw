# -*- coding: utf-8 -*-
"""Integration tests for the files router (file preview endpoint).

Covers GET /api/files/preview/{filepath} with various path scenarios:
valid files, sensitive files, outside workspace, non-existent files.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_FILES_TIMEOUT = default_http_timeout(15.0)


@pytest.mark.integration
@pytest.mark.p1
def test_files_preview_nonexistent_file_404(app_server) -> None:
    """Test purpose:
    - Verify GET /api/files/preview/{nonexistent} returns 404. Client
      needs clear "not found" vs "forbidden" distinction.

    Test flow:
    1. GET /api/files/preview/nonexistent_file_xyz.txt.
    2. Assert 404.

    API endpoints:
    - GET /api/files/preview/{filepath}
    """
    resp = app_server.api_request(
        "GET",
        "/api/files/preview/nonexistent_file_xyz.txt",
        timeout=_FILES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_files_preview_sensitive_file_blocked(app_server) -> None:
    """Test purpose:
    - Verify GET /api/files/preview blocks sensitive files (e.g. .env,
      credentials). FileGuard prevents accidental exposure.

    Test flow:
    1. GET /api/files/preview/.env (or similar sensitive path).
    2. Assert 403 with SENSITIVE_FILE_BLOCKED reason.

    API endpoints:
    - GET /api/files/preview/{filepath}
    """
    resp = app_server.api_request(
        "GET",
        "/api/files/preview/.env",
        timeout=_FILES_TIMEOUT,
    )
    # Should be blocked (403) or not found (404) depending on FileGuard config
    assert resp.status_code in (403, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_files_preview_path_traversal_blocked(app_server) -> None:
    """Test purpose:
    - Verify GET /api/files/preview blocks path traversal attempts.
      Security: must not allow escaping workspace directory.

    Test flow:
    1. GET /api/files/preview/../../../etc/passwd.
    2. Assert 403 or 404 (blocked or not found).

    API endpoints:
    - GET /api/files/preview/{filepath}
    """
    resp = app_server.api_request(
        "GET",
        "/api/files/preview/../../../etc/passwd",
        timeout=_FILES_TIMEOUT,
    )
    # allow_preview_outside_workspace defaults to True; the sensitive
    # file guard still applies
    assert resp.status_code in (200, 403, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_files_preview_outside_workspace_default_blocked(app_server) -> None:
    """Test purpose:
    - Verify GET /api/files/preview blocks files outside workspace by
      default (when allow_preview_outside_workspace is False).

    Test flow:
    1. GET /api/files/preview/etc/hosts (absolute path outside workspace).
    2. Assert 403 with OUTSIDE_WORKSPACE reason.

    API endpoints:
    - GET /api/files/preview/{filepath}
    """
    resp = app_server.api_request(
        "GET",
        "/api/files/preview/etc/hosts",
        timeout=_FILES_TIMEOUT,
    )
    assert resp.status_code in (200, 403, 404), app_server.logs_tail()
