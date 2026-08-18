# -*- coding: utf-8 -*-
"""MCP access-policy persistence and principal listing.

Covers the policy surface of ``app/routers/mcp.py`` and
``app/mcp/config_service.py`` that existing MCP tests do not touch: the
saved access policy round trip (default effect plus tool defaults), the
recent-principal listing used by the policy editor, and the guards for
an unknown client key and an invalid effect value.

All work happens on an MCP client this module creates and deletes, and
the client uses a trivial stdio command that is never launched by these
endpoints, so nothing external is contacted.

API endpoints:
  - POST   /api/mcp
  - DELETE /api/mcp/{client_key}
  - GET    /api/mcp/policy/{client_key}
  - PUT    /api/mcp/policy/{client_key}
  - GET    /api/mcp/access-principals
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

_CLIENT_KEY = "integ-mcp-policy-client"
_ABSENT_CLIENT = "integ-absent-mcp-policy-8842"


@pytest.fixture
def mcp_client(app_server):
    """Create a throwaway MCP client; remove it afterwards."""
    app_server.api_request(
        "DELETE",
        f"/api/mcp/{_CLIENT_KEY}",
        timeout=_HTTP_TIMEOUT,
    )
    created = app_server.api_request(
        "POST",
        "/api/mcp",
        json={
            "client_key": _CLIENT_KEY,
            "client": {
                "name": "integ mcp policy client",
                "description": "created by integration tests",
                "enabled": True,
                "transport": "stdio",
                "command": "echo",
                "args": ["mcp"],
            },
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text
    yield _CLIENT_KEY
    app_server.api_request(
        "DELETE",
        f"/api/mcp/{_CLIENT_KEY}",
        timeout=_HTTP_TIMEOUT,
    )


# ============================ A. policy round trip =========================


@pytest.mark.integration
@pytest.mark.p1
def test_policy_default_effect_roundtrip(
    app_server,
    mcp_client,  # pylint: disable=redefined-outer-name
):
    """The saved default effect persists across PUT/GET.

    Test purpose:
      - Cover get_mcp_policy / update_mcp_policy plus
        mcp_access_policy_from_card: the console-managed default effect
        must be written into the driver card's policy and read back
        unchanged.

    Test flow:
      1. GET the policy for a fresh client as a baseline.
      2. PUT a different default_effect and assert GET reflects it.
    """
    before = app_server.api_request(
        "GET",
        f"/api/mcp/policy/{mcp_client}",
        timeout=_HTTP_TIMEOUT,
    )
    assert before.status_code == 200, before.text
    baseline = before.json()
    assert "default_effect" in baseline, baseline

    target = "ask" if baseline["default_effect"] != "ask" else "allow"
    patched = dict(baseline)
    patched["default_effect"] = target

    put_resp = app_server.api_request(
        "PUT",
        f"/api/mcp/policy/{mcp_client}",
        json=patched,
        timeout=_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json()["default_effect"] == target, put_resp.json()

    after = app_server.api_request(
        "GET",
        f"/api/mcp/policy/{mcp_client}",
        timeout=_HTTP_TIMEOUT,
    )
    assert after.json()["default_effect"] == target, after.json()


@pytest.mark.integration
@pytest.mark.p1
def test_policy_tool_default_is_persisted(
    app_server,
    mcp_client,  # pylint: disable=redefined-outer-name
):
    """A per-tool default effect survives the round trip.

    Test purpose:
      - Cover the tool_defaults arm of the policy translation
        (_mcp_tool_default_from_rule and its writer), which is a
        separate code path from the client-wide default effect.
    """
    baseline = app_server.api_request(
        "GET",
        f"/api/mcp/policy/{mcp_client}",
        timeout=_HTTP_TIMEOUT,
    ).json()
    patched = dict(baseline)
    patched["tool_defaults"] = [
        {"tool_name": "integ_probe_tool", "effect": "deny"},
    ]

    put_resp = app_server.api_request(
        "PUT",
        f"/api/mcp/policy/{mcp_client}",
        json=patched,
        timeout=_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, put_resp.text

    after = app_server.api_request(
        "GET",
        f"/api/mcp/policy/{mcp_client}",
        timeout=_HTTP_TIMEOUT,
    )
    assert after.status_code == 200, after.text
    defaults = {
        item["tool_name"]: item["effect"]
        for item in after.json().get("tool_defaults") or []
    }
    assert defaults.get("integ_probe_tool") == "deny", after.json()


@pytest.mark.integration
@pytest.mark.p2
def test_policy_rejects_invalid_effect(
    app_server,
    mcp_client,  # pylint: disable=redefined-outer-name
):
    """An unsupported effect value is rejected by validation.

    Test purpose:
      - Cover the Literal constraint on default_effect so an unknown
        verdict cannot be persisted and later misinterpreted at
        enforcement time.
    """
    resp = app_server.api_request(
        "PUT",
        f"/api/mcp/policy/{mcp_client}",
        json={"default_effect": "integ-not-an-effect"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text
    # The stored value must remain one of the supported effects.
    after = app_server.api_request(
        "GET",
        f"/api/mcp/policy/{mcp_client}",
        timeout=_HTTP_TIMEOUT,
    )
    assert after.json()["default_effect"] in (
        "allow",
        "ask",
        "deny",
    ), after.json()


@pytest.mark.integration
@pytest.mark.p2
def test_policy_for_unknown_client_is_handled(app_server):
    """Reading a policy for an unknown client does not 500.

    Test purpose:
      - Cover the client-lookup path in get_policy for a key that was
        never registered.
    """
    resp = app_server.api_request(
        "GET",
        f"/api/mcp/policy/{_ABSENT_CLIENT}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 400, 404), resp.text
    assert resp.status_code != 500, resp.text


# =========================== B. access principals ==========================


@pytest.mark.integration
@pytest.mark.p2
def test_access_principals_listing(app_server):
    """The principal catalogue answers with a well-formed list.

    Test purpose:
      - Cover list_access_principals / _principal_option_label, which
        the policy editor uses to offer source-scoped subjects. The list
        is legitimately empty on a fresh workspace.
    """
    resp = app_server.api_request(
        "GET",
        "/api/mcp/access-principals",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    options = resp.json()
    assert isinstance(options, list), options
    for option in options:
        assert isinstance(option, dict), option
