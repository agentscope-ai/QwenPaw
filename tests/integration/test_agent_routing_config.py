# -*- coding: utf-8 -*-
"""Smoke tests for ACP, LLM routing, allow-no-auth, timezone."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_acp_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped ACP config endpoint supports full payload update and
      readback.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped ACP config as baseline.
    3. PUT scoped ACP config with one agent's enabled flag toggled.
    4. GET scoped ACP config and verify the update is persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/acp
    - PUT /api/agents/{agentId}/config/acp
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_acp_01"
    endpoint = f"/api/agents/{agent_id}/config/acp"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Scoped ACP agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline = None
    changed_agent = None
    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        agents = baseline.get("agents")
        assert isinstance(agents, dict) and agents
        changed_agent = next(iter(agents.keys()))

        updated = {"agents": {}}
        for name, cfg in agents.items():
            cfg_dict = dict(cfg)
            if name == changed_agent:
                cfg_dict["enabled"] = not bool(cfg_dict.get("enabled", False))
            updated["agents"][name] = cfg_dict

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(
            put_resp.json()
            .get("agents", {})
            .get(changed_agent, {})
            .get("enabled", False),
        ) == bool(updated["agents"][changed_agent]["enabled"])

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert bool(
            get_after.json()
            .get("agents", {})
            .get(changed_agent, {})
            .get("enabled", False),
        ) == bool(updated["agents"][changed_agent]["enabled"])
    finally:
        if isinstance(baseline, dict):
            restore = app_server.api_request("PUT", endpoint, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_acp_single_agent_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped ACP single-agent endpoint supports update and
      readback for one ACP agent entry.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped ACP and pick one existing ACP agent key.
    3. GET scoped ACP single-agent config as baseline.
    4. PUT scoped single-agent config with toggled enabled value.
    5. GET again and verify update persisted.
    6. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/acp
    - GET /api/agents/{agentId}/config/acp/{agent_name}
    - PUT /api/agents/{agentId}/config/acp/{agent_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_acp_agent_01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped ACP single agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    acp_agent_name = None
    baseline = None
    try:
        get_acp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/config/acp",
        )
        assert get_acp.status_code == 200, app_server.logs_tail()
        agents = get_acp.json().get("agents")
        assert isinstance(agents, dict) and agents
        acp_agent_name = next(iter(agents.keys()))

        endpoint = f"/api/agents/{agent_id}/config/acp/{acp_agent_name}"
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "enabled" in baseline
        assert "tool_parse_mode" in baseline

        updated = dict(baseline)
        updated["enabled"] = not bool(baseline.get("enabled", False))

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled", False)) == bool(
            updated["enabled"],
        )

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert bool(get_after.json().get("enabled", False)) == bool(
            updated["enabled"],
        )
    finally:
        if acp_agent_name and isinstance(baseline, dict):
            endpoint = f"/api/agents/{agent_id}/config/acp/{acp_agent_name}"
            restore = app_server.api_request("PUT", endpoint, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_llm_routing_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped llm-routing endpoint supports update and readback.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped llm-routing config as baseline.
    3. PUT scoped llm-routing with toggled ``enabled`` value.
    4. GET scoped llm-routing and verify updated value persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/agents/llm-routing
    - PUT /api/agents/{agentId}/config/agents/llm-routing
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_llm_routing_01"
    endpoint = f"/api/agents/{agent_id}/config/agents/llm-routing"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped llm routing agent",
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
        assert "mode" in baseline
        assert "local" in baseline

        updated = dict(baseline)
        updated["enabled"] = not bool(baseline.get("enabled", False))

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled", False)) == bool(
            updated["enabled"],
        )

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert bool(get_after.json().get("enabled", False)) == bool(
            updated["enabled"],
        )
    finally:
        if isinstance(baseline, dict):
            restore = app_server.api_request("PUT", endpoint, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_global_allow_no_auth_hosts_normalization_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify allow-no-auth-hosts update path normalizes (trim/dedup) valid IPs
      and supports readback.

    Test flow:
    1. GET current allow-no-auth-hosts list.
    2. PUT a list with duplicates and whitespace around valid IPs.
    3. Assert response is normalized and deduplicated.
    4. GET again and assert persisted hosts match normalized result.
    5. Restore original hosts.

    API endpoints:
    - GET /api/config/security/allow-no-auth-hosts
    - PUT /api/config/security/allow-no-auth-hosts
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/allow-no-auth-hosts",
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before_hosts = get_before.json().get("hosts")
    assert isinstance(before_hosts, list)

    update_body = {"hosts": [" 127.0.0.1 ", "::1", "127.0.0.1", "  ::1  "]}

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/allow-no-auth-hosts",
            json=update_body,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        put_hosts = put_resp.json().get("hosts")
        assert put_hosts == ["127.0.0.1", "::1"]

        get_after = app_server.api_request(
            "GET",
            "/api/config/security/allow-no-auth-hosts",
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("hosts") == ["127.0.0.1", "::1"]
    finally:
        restore = app_server.api_request(
            "PUT",
            "/api/config/security/allow-no-auth-hosts",
            json={"hosts": before_hosts},
        )
        assert restore.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_global_allow_no_auth_hosts_reject_invalid_ip(app_server) -> None:
    """Test purpose:
    - Verify allow-no-auth-hosts rejects invalid IP literals with 400.

    Test flow:
    1. PUT hosts payload containing an invalid IP token.
    2. Assert 400 status and error detail mentions invalid IP.

    API endpoints:
    - PUT /api/config/security/allow-no-auth-hosts
    """
    bad_resp = app_server.api_request(
        "PUT",
        "/api/config/security/allow-no-auth-hosts",
        json={"hosts": ["127.0.0.1", "bad-ip-value"]},
    )
    assert bad_resp.status_code == 400, app_server.logs_tail()
    detail = bad_resp.json().get("detail", "")
    assert "Invalid IP address" in detail


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_allow_no_auth_hosts_put_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped allow-no-auth-hosts endpoint supports update and
      readback with normalized values.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped allow-no-auth-hosts as baseline.
    3. PUT scoped hosts payload with duplicates and whitespace.
    4. GET again and verify normalized hosts persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/security/allow-no-auth-hosts
    - PUT /api/agents/{agentId}/config/security/allow-no-auth-hosts
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_allow_no_auth_01"
    endpoint = f"/api/agents/{agent_id}/config/security/allow-no-auth-hosts"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped allow-no-auth agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    before_hosts = None
    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        before_hosts = get_before.json().get("hosts")
        assert isinstance(before_hosts, list)

        put_resp = app_server.api_request(
            "PUT",
            endpoint,
            json={"hosts": [" 127.0.0.1 ", " ::1 ", "127.0.0.1"]},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("hosts") == ["127.0.0.1", "::1"]

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert get_after.json().get("hosts") == ["127.0.0.1", "::1"]
    finally:
        if isinstance(before_hosts, list):
            restore = app_server.api_request(
                "PUT",
                endpoint,
                json={"hosts": before_hosts},
            )
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_user_timezone_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped user-timezone GET/PUT roundtrip and that the value
      is reflected on the global config endpoint (scoped routes share root
      ``user_timezone``).

    Test flow:
    1. Record global user timezone as baseline.
    2. Create a dedicated test agent.
    3. PUT scoped user-timezone with a different valid IANA id.
    4. GET scoped and global endpoints; assert normalized timezone matches.
    5. Restore baseline via global PUT and delete the test agent.

    API endpoints:
    - GET /api/config/user-timezone
    - PUT /api/config/user-timezone
    - POST /api/agents
    - GET /api/agents/{agentId}/config/user-timezone
    - PUT /api/agents/{agentId}/config/user-timezone
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_user_tz_01"
    global_tz = "/api/config/user-timezone"
    scoped_tz = f"/api/agents/{agent_id}/config/user-timezone"

    get_baseline = app_server.api_request("GET", global_tz)
    assert get_baseline.status_code == 200, app_server.logs_tail()
    baseline = get_baseline.json().get("timezone")
    assert isinstance(baseline, str) and baseline

    alternate = "UTC" if baseline != "UTC" else "Asia/Shanghai"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped user timezone agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        put_resp = app_server.api_request(
            "PUT",
            scoped_tz,
            json={"timezone": alternate},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        resolved = put_resp.json().get("timezone")
        assert isinstance(resolved, str) and resolved

        get_scoped = app_server.api_request("GET", scoped_tz)
        assert get_scoped.status_code == 200, app_server.logs_tail()
        assert get_scoped.json().get("timezone") == resolved

        get_global_after = app_server.api_request("GET", global_tz)
        assert get_global_after.status_code == 200, app_server.logs_tail()
        assert get_global_after.json().get("timezone") == resolved
    finally:
        restore = app_server.api_request(
            "PUT",
            global_tz,
            json={"timezone": baseline},
        )
        assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
