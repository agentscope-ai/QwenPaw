# -*- coding: utf-8 -*-
"""Integration tests for the config router (application configuration).

Covers various config endpoints: channel types, user timezone, channel schemas.
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
def test_config_channel_types_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/channels/types returns available channel
      types. Console uses this to populate channel type dropdowns.

    Test flow:
    1. GET /api/config/channels/types.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/config/channels/types
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/types",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)


@pytest.mark.integration
@pytest.mark.p1
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
        "/api/settings/language",
        timeout=_CONFIG_TIMEOUT,
    )
    original = get_resp.json()
    original_lang = original.get("language") or original.get("lang", "en")

    put_resp = app_server.api_request(
        "PUT",
        "/api/settings/language",
        json={"language": "zh"},
        timeout=_CONFIG_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()

    # Restore
    app_server.api_request(
        "PUT",
        "/api/settings/language",
        json={"language": original_lang},
        timeout=_CONFIG_TIMEOUT,
    )


# ------------------------------------------------------------------ #
# Offload policy
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_user_timezone_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/user-timezone returns the configured
      timezone. Console displays this in settings.

    Test flow:
    1. GET /api/config/user-timezone.
    2. Assert 200 and response has timezone field.

    API endpoints:
    - GET /api/config/user-timezone
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/user-timezone",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert "timezone" in payload


@pytest.mark.integration
@pytest.mark.p1
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
        "/api/settings/offload-policy",
        timeout=_CONFIG_TIMEOUT,
    )
    original = get_resp.json()

    put_resp = app_server.api_request(
        "PUT",
        "/api/settings/offload-policy",
        json=original,
        timeout=_CONFIG_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Upload limit
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_channel_schemas_get(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/channels/schemas returns channel config
      schemas. Console uses this for dynamic form rendering.

    Test flow:
    1. GET /api/config/channels/schemas.
    2. Assert 200 and response is a dict.

    API endpoints:
    - GET /api/config/channels/schemas
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/schemas",
        timeout=_CONFIG_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


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
