# -*- coding: utf-8 -*-
"""HTTP smoke tests for heartbeat config (global + agent-scoped)."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_global_heartbeat_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify global heartbeat config can be updated and read back.

    Test flow:
    1. GET current /api/config/heartbeat payload.
    2. Build an update payload by toggling ``enabled``.
    3. PUT updated payload to /api/config/heartbeat.
    4. GET /api/config/heartbeat and verify the updated ``enabled`` value.
    5. PUT original payload back to avoid cross-step surprises.

    API endpoints:
    - GET /api/config/heartbeat
    - PUT /api/config/heartbeat
    """
    get_before = app_server.api_request("GET", "/api/config/heartbeat")
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "enabled" in before
    assert "every" in before
    assert "target" in before

    updated = dict(before)
    updated["enabled"] = not bool(before.get("enabled", False))

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/heartbeat",
            json=updated,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        put_payload = put_resp.json()
        assert put_payload.get("enabled") == updated["enabled"]

        get_after = app_server.api_request("GET", "/api/config/heartbeat")
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("enabled") == updated["enabled"]
        for k, v in before.items():
            if k != "enabled":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        restore_resp = app_server.api_request(
            "PUT",
            "/api/config/heartbeat",
            json=before,
        )
        assert restore_resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_agent_scoped_heartbeat_isolated_from_global(app_server) -> None:
    """Test purpose:
    - Verify updating heartbeat via agent-scoped config does not mutate the
      global config heartbeat for other agents.

    Test flow:
    1. GET global heartbeat baseline from /api/config/heartbeat.
    2. Create a dedicated test agent.
    3. GET scoped heartbeat from /api/agents/{agentId}/config/heartbeat.
    4. PUT scoped heartbeat with toggled ``enabled`` value.
    5. GET scoped heartbeat again and verify update is applied.
    6. GET global heartbeat again and verify baseline value is unchanged.
    7. Delete test agent.

    API endpoints:
    - GET /api/config/heartbeat
    - POST /api/agents
    - GET /api/agents/{agentId}/config/heartbeat
    - PUT /api/agents/{agentId}/config/heartbeat
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_hb_01"

    global_before = app_server.api_request("GET", "/api/config/heartbeat")
    assert global_before.status_code == 200, app_server.logs_tail()
    global_before_payload = global_before.json()
    assert isinstance(global_before_payload, dict)
    assert "enabled" in global_before_payload

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped heartbeat agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        scoped_before = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/config/heartbeat",
        )
        assert scoped_before.status_code == 200, app_server.logs_tail()
        scoped_before_payload = scoped_before.json()
        assert isinstance(scoped_before_payload, dict)
        assert "enabled" in scoped_before_payload
        assert "every" in scoped_before_payload
        assert "target" in scoped_before_payload

        scoped_updated = dict(scoped_before_payload)
        scoped_updated["enabled"] = not bool(
            scoped_before_payload.get("enabled", False),
        )

        put_scoped = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/config/heartbeat",
            json=scoped_updated,
        )
        assert put_scoped.status_code == 200, app_server.logs_tail()
        assert put_scoped.json().get("enabled") == scoped_updated["enabled"]

        scoped_after = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/config/heartbeat",
        )
        assert scoped_after.status_code == 200, app_server.logs_tail()
        assert scoped_after.json().get("enabled") == scoped_updated["enabled"]

        global_after = app_server.api_request("GET", "/api/config/heartbeat")
        assert global_after.status_code == 200, app_server.logs_tail()
        assert global_after.json().get("enabled") == global_before_payload.get(
            "enabled",
        )
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_heartbeat_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped heartbeat endpoint itself supports update and
      readback in a stable roundtrip.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped heartbeat config as baseline.
    3. PUT scoped heartbeat with toggled ``enabled`` value.
    4. GET scoped heartbeat and verify the new value is persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/heartbeat
    - PUT /api/agents/{agentId}/config/heartbeat
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_hb_roundtrip_01"
    endpoint = f"/api/agents/{agent_id}/config/heartbeat"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped heartbeat roundtrip agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline = None
    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "enabled" in baseline
        assert "every" in baseline
        assert "target" in baseline

        updated = dict(baseline)
        updated["enabled"] = not bool(baseline.get("enabled", False))

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("enabled") == updated["enabled"]

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("enabled") == updated["enabled"]
        for k, v in baseline.items():
            if k != "enabled":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        if isinstance(baseline, dict):
            restore = app_server.api_request("PUT", endpoint, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
