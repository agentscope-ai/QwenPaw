# -*- coding: utf-8 -*-
"""HTTP smoke tests for workspace running_config (global + agent-scoped)."""
from __future__ import annotations


import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_api_workspace_running_config_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify workspace running-config supports update and readback for the
      active agent context.

    Test flow:
    1. Create a dedicated test agent.
    2. GET /api/workspace/running-config as baseline.
    3. PUT /api/workspace/running-config with a toggled max_iters value.
    4. GET /api/workspace/running-config and verify update is persisted.
    5. Restore baseline value and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/workspace/running-config
    - PUT /api/workspace/running-config
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_running_cfg_01"
    headers = {"X-Agent-Id": agent_id}

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace running config agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline = None
    try:
        get_before = app_server.api_request(
            "GET",
            "/api/workspace/running-config",
            headers=headers,
        )
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "max_iters" in baseline

        updated = dict(baseline)
        old_max_iters = int(updated.get("max_iters", 100))
        updated["max_iters"] = (
            old_max_iters + 1 if old_max_iters < 1000 else old_max_iters - 1
        )

        put_resp = app_server.api_request(
            "PUT",
            "/api/workspace/running-config",
            headers=headers,
            json=updated,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("max_iters") == updated["max_iters"]

        get_after = app_server.api_request(
            "GET",
            "/api/workspace/running-config",
            headers=headers,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("max_iters") == updated["max_iters"]
    finally:
        if isinstance(baseline, dict):
            restore_resp = app_server.api_request(
                "PUT",
                "/api/workspace/running-config",
                headers=headers,
                json=baseline,
            )
            assert restore_resp.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_agent_scoped_workspace_running_config_put_get_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify agent-scoped workspace running-config endpoint supports update and
      readback via /api/agents/{agentId}/workspace/running-config.

    Test flow:
    1. Create a dedicated test agent.
    2. GET agent-scoped running-config as baseline.
    3. PUT agent-scoped running-config with a changed max_iters value.
    4. GET again and assert the value is persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/running-config
    - PUT /api/agents/{agentId}/workspace/running-config
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_ws_running_cfg_01"
    base = f"/api/agents/{agent_id}/workspace/running-config"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped workspace running config agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline = None
    try:
        get_before = app_server.api_request("GET", base)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "max_iters" in baseline

        updated = dict(baseline)
        old_max_iters = int(updated.get("max_iters", 100))
        updated["max_iters"] = (
            old_max_iters + 2 if old_max_iters < 999 else old_max_iters - 2
        )

        put_resp = app_server.api_request("PUT", base, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("max_iters") == updated["max_iters"]

        get_after = app_server.api_request("GET", base)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("max_iters") == updated["max_iters"]
    finally:
        if isinstance(baseline, dict):
            restore_resp = app_server.api_request("PUT", base, json=baseline)
            assert restore_resp.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
