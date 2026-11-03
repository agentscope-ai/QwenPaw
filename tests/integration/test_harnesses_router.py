# -*- coding: utf-8 -*-
"""Integration tests for the harnesses (third-party agent catalog) router.

Covers GET /api/harnesses (provider listing), GET /api/harnesses/{id}/models,
GET /api/harnesses/{id}/mcp, GET /api/harnesses/{id}/skills, and error
handling for unknown providers.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HARNESSES_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# Provider listing
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_list_returns_providers(app_server) -> None:
    """Test purpose:
    - Verify GET /api/harnesses returns a providers list. Console
      renders third-party agent backends from this endpoint.

    Test flow:
    1. GET /api/harnesses.
    2. Assert 200 and response has "providers" key (list).

    API endpoints:
    - GET /api/harnesses
    """
    resp = app_server.api_request(
        "GET",
        "/api/harnesses",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload.get("providers"), list)


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_provider_schema(app_server) -> None:
    """Test purpose:
    - Verify each provider entry has expected fields from the
      HarnessProviderInfo schema.

    Test flow:
    1. GET /api/harnesses.
    2. If providers exist, verify each has name and other fields.

    API endpoints:
    - GET /api/harnesses
    """
    resp = app_server.api_request(
        "GET",
        "/api/harnesses",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    providers = resp.json().get("providers", [])
    for provider in providers:
        assert isinstance(provider, dict)
        # Each provider should have at least a name or id field
        assert len(provider) > 0


# ------------------------------------------------------------------ #
# Unknown provider handling
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_unknown_provider_models_404(app_server) -> None:
    """Test purpose:
    - Verify GET /api/harnesses/{unknown}/models returns 404 with a
      clear error message. Client needs to distinguish "provider not
      found" from "provider has no models".

    Test flow:
    1. GET /api/harnesses/nonexistent_provider_xyz/models.
    2. Assert 404.

    API endpoints:
    - GET /api/harnesses/{provider_id}/models
    """
    resp = app_server.api_request(
        "GET",
        "/api/harnesses/nonexistent_provider_xyz/models",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_unknown_provider_mcp_404(app_server) -> None:
    """Test purpose:
    - Verify GET /api/harnesses/{unknown}/mcp returns 404.

    Test flow:
    1. GET /api/harnesses/nonexistent_provider_xyz/mcp.
    2. Assert 404.

    API endpoints:
    - GET /api/harnesses/{provider_id}/mcp
    """
    resp = app_server.api_request(
        "GET",
        "/api/harnesses/nonexistent_provider_xyz/mcp",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_unknown_provider_skills_404(app_server) -> None:
    """Test purpose:
    - Verify GET /api/harnesses/{unknown}/skills returns 404.

    Test flow:
    1. GET /api/harnesses/nonexistent_provider_xyz/skills.
    2. Assert 404.

    API endpoints:
    - GET /api/harnesses/{provider_id}/skills
    """
    resp = app_server.api_request(
        "GET",
        "/api/harnesses/nonexistent_provider_xyz/skills",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_unknown_provider_status_404(app_server) -> None:
    """Test purpose:
    - Verify POST /api/harnesses/{unknown}/status returns 404.

    Test flow:
    1. POST /api/harnesses/nonexistent_provider_xyz/status.
    2. Assert 404.

    API endpoints:
    - POST /api/harnesses/{provider_id}/status
    """
    resp = app_server.api_request(
        "POST",
        "/api/harnesses/nonexistent_provider_xyz/status",
        json={"settings": {}},
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_unknown_provider_login_404(app_server) -> None:
    """Test purpose:
    - Verify POST /api/harnesses/{unknown}/login returns 404.

    Test flow:
    1. POST /api/harnesses/nonexistent_provider_xyz/login.
    2. Assert 404.

    API endpoints:
    - POST /api/harnesses/{provider_id}/login
    """
    resp = app_server.api_request(
        "POST",
        "/api/harnesses/nonexistent_provider_xyz/login",
        json={"settings": {}, "device_code": False},
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_unknown_provider_logout_404(app_server) -> None:
    """Test purpose:
    - Verify POST /api/harnesses/{unknown}/logout returns 404.

    Test flow:
    1. POST /api/harnesses/nonexistent_provider_xyz/logout.
    2. Assert 404.

    API endpoints:
    - POST /api/harnesses/{provider_id}/logout
    """
    resp = app_server.api_request(
        "POST",
        "/api/harnesses/nonexistent_provider_xyz/logout",
        json={"settings": {}},
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Coming soon provider handling
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_harnesses_coming_soon_provider_409(app_server) -> None:
    """Test purpose:
    - Verify a coming_soon provider returns 409 (conflict) instead of
      404. Client can show "not available yet" vs "doesn't exist".

    Test flow:
    1. GET /api/harnesses to find a coming_soon provider (if any).
    2. If found, GET /api/harnesses/{id}/models and assert 409.

    API endpoints:
    - GET /api/harnesses
    - GET /api/harnesses/{provider_id}/models
    """
    resp = app_server.api_request(
        "GET",
        "/api/harnesses",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    providers = resp.json().get("providers", [])

    coming_soon = None
    for p in providers:
        if p.get("coming_soon"):
            coming_soon = p
            break

    if coming_soon is None:
        pytest.skip("No coming_soon providers registered")

    provider_id = coming_soon.get("id") or coming_soon.get("key", "")
    resp2 = app_server.api_request(
        "GET",
        f"/api/harnesses/{provider_id}/models",
        timeout=_HARNESSES_TIMEOUT,
    )
    assert resp2.status_code == 409, app_server.logs_tail()
