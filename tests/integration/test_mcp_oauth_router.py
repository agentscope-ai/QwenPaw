# -*- coding: utf-8 -*-
"""MCP OAuth callback, status and revoke endpoints.

Covers ``app/routers/mcp_oauth.py``'s HTTP surface without contacting any
external identity provider: the authorization-callback error pages
(provider-reported error, missing parameters, unknown/expired state), the
per-client token status read for a client that was never authorized, the
revoke path, and the start endpoint's validation guards.

The callback tests assert the rendered page content (an error page, not a
success page) so a regression that silently reports success on a failed
authorization is caught. No test supplies a usable authorization code, so
no token exchange is ever attempted.

API endpoints:
  - GET    /api/mcp/oauth/callback
  - GET    /api/mcp/oauth/status/{client_key}
  - DELETE /api/mcp/oauth/{client_key}
  - POST   /api/mcp/oauth/start/{client_key}
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

_ABSENT_CLIENT = "integ-absent-mcp-client-4417"


# ========================== A. callback error pages ========================


@pytest.mark.integration
@pytest.mark.p1
def test_callback_renders_error_page_for_provider_error(app_server):
    """A provider-reported error renders the error page, not success.

    Test purpose:
      - Cover oauth_callback's ``error`` short-circuit, which must
        surface the provider's description without attempting a token
        exchange.
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/oauth/callback",
        params={
            "error": "access_denied",
            "error_description": "integ user declined consent",
        },
        timeout=_HTTP_TIMEOUT,
    )
    # _make_error_page returns the popup HTML with status 400.
    assert resp.status_code == 400, resp.text[:500]
    assert "integ user declined consent" in resp.text, resp.text[:800]
    assert "Authorization successful" not in resp.text, resp.text[:800]


@pytest.mark.integration
@pytest.mark.p2
def test_callback_without_code_or_state_is_error_page(app_server):
    """A callback missing code/state is refused.

    Test purpose:
      - Cover the "Missing 'code' or 'state'" guard, distinct from the
        provider-error branch above.
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/oauth/callback",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text[:500]
    assert "Missing" in resp.text, resp.text[:800]
    assert "Authorization successful" not in resp.text, resp.text[:800]


@pytest.mark.integration
@pytest.mark.p1
def test_callback_with_unknown_state_is_error_page(app_server):
    """An unrecognised state value cannot complete a flow.

    Test purpose:
      - Cover the state-store lookup miss, which is the guard against a
        forged or replayed callback. A regression here would let an
        attacker-supplied code be exchanged against no session.
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/oauth/callback",
        params={
            "code": "integ-fake-code",
            "state": "integ-state-that-was-never-issued",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, resp.text[:500]
    lowered = resp.text.lower()
    assert "expired" in lowered or "not found" in lowered, resp.text[:800]
    assert "Authorization successful" not in resp.text, resp.text[:800]


# ======================== B. status / revoke branches ======================


@pytest.mark.integration
@pytest.mark.p2
def test_status_for_unknown_client_is_handled(app_server):
    """Status for a client that does not exist is handled cleanly.

    Test purpose:
      - Cover _load_mcp_card_for_oauth's missing-card branch reached
        from the status route; it must not 500.
    """
    resp = app_server.api_request(
        "GET",
        f"/api/mcp/oauth/status/{_ABSENT_CLIENT}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), resp.text
    if resp.status_code == 200:
        assert resp.json().get("authorized") is False, resp.json()


@pytest.mark.integration
@pytest.mark.p2
def test_revoke_unknown_client_is_handled(app_server):
    """Revoking tokens for an unknown client does not 500.

    Test purpose:
      - Cover oauth_revoke's card-lookup path for a client with no
        stored credential; deleting nothing must be safe.
    """
    resp = app_server.api_request(
        "DELETE",
        f"/api/mcp/oauth/{_ABSENT_CLIENT}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), resp.text
    assert resp.status_code != 500, resp.text


# =========================== C. start validation ===========================


@pytest.mark.integration
@pytest.mark.p2
def test_start_without_url_is_rejected(app_server):
    """Starting a flow with no remote URL is refused.

    Test purpose:
      - Cover oauth_start's "must have a remote URL" guard, which runs
        before any endpoint discovery so no network call is made.
    """
    resp = app_server.api_request(
        "POST",
        f"/api/mcp/oauth/start/{_ABSENT_CLIENT}",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 404, 422), resp.text
    assert resp.status_code != 500, resp.text
