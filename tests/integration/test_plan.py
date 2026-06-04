# -*- coding: utf-8 -*-
"""Integration tests for plan APIs."""
from __future__ import annotations

import pytest

_PLAN_HTTP_TIMEOUT = 20.0


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_plan_config_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped plan config supports update, readback, and restore
      of the original payload.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped plan config and store baseline ``enabled``.
    3. PUT scoped config with toggled ``enabled`` and GET to verify.
    4. PUT scoped baseline payload back and GET to verify restoration.
    5. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/plan/config
    - PUT /api/agents/{agentId}/plan/config
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_plan_scoped_roundtrip_01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Plan scoped roundtrip agent",
            "description": "",
        },
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        get_before = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "enabled" in baseline

        toggled = {"enabled": not bool(baseline.get("enabled", False))}
        put_toggle = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/plan/config",
            json=toggled,
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert put_toggle.status_code == 200, app_server.logs_tail()
        assert put_toggle.json().get("enabled") == toggled["enabled"]

        get_mid = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert get_mid.status_code == 200, app_server.logs_tail()
        assert get_mid.json().get("enabled") == toggled["enabled"]

        restore = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/plan/config",
            json=baseline,
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert restore.status_code == 200, app_server.logs_tail()
        assert restore.json().get("enabled") == baseline.get("enabled")

        get_after = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("enabled") == baseline.get("enabled")
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_PLAN_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p0
def test_plan_config_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify global plan config supports update and readback.

    Test flow:
    1. GET /api/plan/config and store baseline ``enabled`` value.
    2. PUT /api/plan/config with toggled ``enabled``.
    3. GET /api/plan/config and verify updated value.
    4. Restore baseline value in finally.

    API endpoints:
    - GET /api/plan/config
    - PUT /api/plan/config
    """
    get_before = app_server.api_request(
        "GET",
        "/api/plan/config",
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "enabled" in before

    updated = {"enabled": not bool(before.get("enabled", False))}

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/plan/config",
            json=updated,
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("enabled") == updated["enabled"]

        get_after = app_server.api_request(
            "GET",
            "/api/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("enabled") == updated["enabled"]
    finally:
        restore_resp = app_server.api_request(
            "PUT",
            "/api/plan/config",
            json={"enabled": bool(before.get("enabled", False))},
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert restore_resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_plan_current_minimal_contract(app_server) -> None:
    """Test purpose:
    - Verify current-plan endpoint remains available with stable shape.

    Test flow:
    1. GET /api/plan/current without session_id.
    2. Accept either ``null`` (no current plan) or an object payload.
    3. If present, verify JSON object (schema is runtime-driven).

    API endpoints:
    - GET /api/plan/current
    """
    resp = app_server.api_request(
        "GET",
        "/api/plan/current",
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert payload is None or isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p2
def test_plan_scoped_config_isolated_from_global(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped plan config updates do not mutate global plan config.

    Test flow:
    1. Read global baseline via /api/plan/config.
    2. Create a dedicated test agent.
    3. Read scoped config via /api/agents/{agentId}/plan/config.
    4. Toggle scoped ``enabled`` via scoped PUT.
    5. Verify scoped GET reflects update.
    6. Verify global GET still matches baseline.
    7. Delete test agent.

    API endpoints:
    - GET /api/plan/config
    - POST /api/agents
    - GET /api/agents/{agentId}/plan/config
    - PUT /api/agents/{agentId}/plan/config
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_plan_scoped_01"

    global_before = app_server.api_request(
        "GET",
        "/api/plan/config",
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert global_before.status_code == 200, app_server.logs_tail()
    global_enabled = bool(global_before.json().get("enabled", False))

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Plan scoped agent", "description": ""},
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        scoped_before = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert scoped_before.status_code == 200, app_server.logs_tail()
        scoped_enabled = bool(scoped_before.json().get("enabled", False))

        scoped_put = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/plan/config",
            json={"enabled": not scoped_enabled},
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert scoped_put.status_code == 200, app_server.logs_tail()
        assert scoped_put.json().get("enabled") == (not scoped_enabled)

        scoped_after = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert scoped_after.status_code == 200, app_server.logs_tail()
        assert scoped_after.json().get("enabled") == (not scoped_enabled)

        global_after = app_server.api_request(
            "GET",
            "/api/plan/config",
            timeout=_PLAN_HTTP_TIMEOUT,
        )
        assert global_after.status_code == 200, app_server.logs_tail()
        assert (
            bool(global_after.json().get("enabled", False)) == global_enabled
        )
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_PLAN_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_plan_scoped_config_missing_agent_returns_404(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped plan config endpoints return 404 for unknown agents.

    Test flow:
    1. GET /api/agents/{agentId}/plan/config with a non-existing agent ID.
    2. PUT /api/agents/{agentId}/plan/config with a non-existing agent ID.
    3. Assert both responses are 404 and include error detail.

    API endpoints:
    - GET /api/agents/{agentId}/plan/config
    - PUT /api/agents/{agentId}/plan/config
    """
    missing_agent_id = "integ_plan_missing_agent_404"

    get_resp = app_server.api_request(
        "GET",
        f"/api/agents/{missing_agent_id}/plan/config",
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 404, app_server.logs_tail()
    assert "detail" in get_resp.json()

    put_resp = app_server.api_request(
        "PUT",
        f"/api/agents/{missing_agent_id}/plan/config",
        json={"enabled": True},
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 404, app_server.logs_tail()
    assert "detail" in put_resp.json()


@pytest.mark.integration
@pytest.mark.p2
def test_plan_config_rejects_invalid_payload(app_server) -> None:
    """Test purpose:
    - Verify global plan config update rejects invalid body schema.

    Test flow:
    1. PUT /api/plan/config with an invalid payload (``enabled`` is not bool).
    2. Assert response is validation error and includes detail field.

    API endpoints:
    - PUT /api/plan/config
    """
    resp = app_server.api_request(
        "PUT",
        "/api/plan/config",
        json={"enabled": "not_bool_value"},
        timeout=_PLAN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()
    assert "detail" in resp.json()
