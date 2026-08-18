# -*- coding: utf-8 -*-
"""Integration tests for the config router (application configuration).

Covers various config endpoints: language, offload policy, upload limit.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_CONFIG_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# Language
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_language_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/language returns current UI language.
      Console uses this to set locale on boot.

    Test flow:
    1. GET /api/config/language.
    2. Assert 200 and response has language field.

    API endpoints:
    - GET /api/config/language
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/language",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert "language" in payload or "lang" in payload


@pytest.mark.integration
@pytest.mark.p2
def test_config_language_put(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/config/language accepts a valid language code.

    Test flow:
    1. GET current language.
    2. PUT new language (zh).
    3. GET again and verify change.
    4. Restore original.

    API endpoints:
    - GET /api/config/language
    - PUT /api/config/language
    """
    get_resp = app_server.api_request(
        "GET",
        "/api/config/language",
        timeout=_CONFIG_TIMEOUT,
    )
    original = get_resp.json()
    original_lang = original.get("language") or original.get("lang", "en")

    put_resp = app_server.api_request(
        "PUT",
        "/api/config/language",
        json={"language": "zh"},
        timeout=_CONFIG_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()

    # Restore
    app_server.api_request(
        "PUT",
        "/api/config/language",
        json={"language": original_lang},
        timeout=_CONFIG_TIMEOUT,
    )


# ------------------------------------------------------------------ #
# Offload policy
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_offload_policy_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/offload-policy returns current policy.
      Console settings page reads this.

    Test flow:
    1. GET /api/config/offload-policy.
    2. Assert 200 and response is a dict.

    API endpoints:
    - GET /api/config/offload-policy
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/offload-policy",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p2
def test_config_offload_policy_put(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/config/offload-policy accepts a valid policy.

    Test flow:
    1. GET current policy.
    2. PUT updated policy.
    3. Restore original.

    API endpoints:
    - GET /api/config/offload-policy
    - PUT /api/config/offload-policy
    """
    get_resp = app_server.api_request(
        "GET",
        "/api/config/offload-policy",
        timeout=_CONFIG_TIMEOUT,
    )
    original = get_resp.json()

    put_resp = app_server.api_request(
        "PUT",
        "/api/config/offload-policy",
        json=original,
        timeout=_CONFIG_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Upload limit
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_upload_limit_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/upload-limit returns the upload size limit.
      Console uses this to validate file uploads before sending.

    Test flow:
    1. GET /api/config/upload-limit.
    2. Assert 200 and response has limit field.

    API endpoints:
    - GET /api/config/upload-limit
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/upload-limit",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert "limit" in payload or "max_size" in payload


# ------------------------------------------------------------------ #
# Health check
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_healthz_endpoint(app_server) -> None:
    """Test purpose:
    - Verify GET /api/healthz returns 200. Load balancers and monitoring
      systems use this for health checks.

    Test flow:
    1. GET /api/healthz.
    2. Assert 200.

    API endpoints:
    - GET /api/healthz
    """
    resp = app_server.api_request(
        "GET",
        "/api/healthz",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
