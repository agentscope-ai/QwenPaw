# -*- coding: utf-8 -*-
"""HTTP smoke tests for agents lifecycle (list/create/update/order/toggle)."""
from __future__ import annotations


import pytest

from qwenpaw.constant import BUILTIN_QA_AGENT_ID

_AGENT_PROFILE_TOP_LEVEL_KEYS = (
    "channels",
    "mcp",
    "heartbeat",
    "running",
    "llm_routing",
    "system_prompt_files",
    "tools",
    "plan",
)


@pytest.mark.integration
@pytest.mark.p0
def test_api_agents_list_create_get_delete(app_server) -> None:
    """Test purpose:
    - Verify the primary Agents management flow works end-to-end: list system
      agents, create one, read details, delete it, and confirm removal.
    - Verify a newly created agent includes required top-level config groups.

    Test flow:
    1. GET /api/agents; confirm list contains ``default`` and builtin QA.
    2. POST /api/agents to create a test agent.
    3. GET /api/agents/{agentId} and validate name plus key config groups.
    4. DELETE /api/agents/{agentId}.
    5. GET /api/agents/{agentId} again and assert 404.

    API endpoints:
    - GET /api/agents
    - POST /api/agents
    - GET /api/agents/{agentId}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_agents_01"

    list_resp = app_server.api_request("GET", "/api/agents")
    assert list_resp.status_code == 200, app_server.logs_tail()
    agents_payload = list_resp.json()
    assert "agents" in agents_payload
    assert isinstance(agents_payload["agents"], list)
    listed_ids = {a["id"] for a in agents_payload["agents"]}
    assert "default" in listed_ids, f"missing default agent in {listed_ids}"
    assert (
        BUILTIN_QA_AGENT_ID in listed_ids
    ), f"missing builtin QA agent in {listed_ids}"

    create_resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Integration smoke agent",
            "description": "",
        },
    )
    assert create_resp.status_code == 201, app_server.logs_tail()
    created = create_resp.json()
    assert created["id"] == agent_id
    assert created.get("enabled") is True
    assert isinstance(created.get("workspace_dir"), str)
    assert created["workspace_dir"].strip()

    try:
        get_resp = app_server.api_request("GET", f"/api/agents/{agent_id}")
        assert get_resp.status_code == 200, app_server.logs_tail()
        profile = get_resp.json()
        assert profile["id"] == agent_id
        assert profile["name"] == "Integration smoke agent"
        missing_keys = [
            k for k in _AGENT_PROFILE_TOP_LEVEL_KEYS if k not in profile
        ]
        assert not missing_keys, (
            f"agent profile missing top-level keys {missing_keys}; "
            f"have {sorted(profile.keys())}"
        )
    finally:
        del_resp = app_server.api_request("DELETE", f"/api/agents/{agent_id}")
        assert del_resp.status_code == 200, app_server.logs_tail()
        assert del_resp.json().get("success") is True

    missing = app_server.api_request("GET", f"/api/agents/{agent_id}")
    assert missing.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_api_agents_update_and_readback(app_server) -> None:
    """Test purpose:
    - Verify full agent updates (PUT) take effect and can be read back via GET.

    Test flow:
    1. POST /api/agents to create a test agent.
    2. GET /api/agents/{agentId} to obtain a complete profile payload.
    3. Update name/description/system_prompt_files and PUT it back.
    4. GET /api/agents/{agentId} again and verify updated fields.
    5. DELETE /api/agents/{agentId} for cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    - PUT /api/agents/{agentId}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_agents_upd_01"
    updated_name = "Integration smoke agent updated"
    updated_desc = "updated by integration test"
    updated_prompt_files = ["AGENTS.md", "PROFILE.md", "SOUL.md"]

    create_resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Integration smoke agent",
            "description": "",
        },
    )
    assert create_resp.status_code == 201, app_server.logs_tail()

    try:
        get_before = app_server.api_request("GET", f"/api/agents/{agent_id}")
        assert get_before.status_code == 200, app_server.logs_tail()
        profile = get_before.json()

        profile["name"] = updated_name
        profile["description"] = updated_desc
        profile["system_prompt_files"] = updated_prompt_files

        put_resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}",
            json=profile,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        put_payload = put_resp.json()
        assert put_payload["id"] == agent_id
        assert put_payload["name"] == updated_name
        assert put_payload["description"] == updated_desc
        assert put_payload["system_prompt_files"] == updated_prompt_files

        get_after = app_server.api_request("GET", f"/api/agents/{agent_id}")
        assert get_after.status_code == 200, app_server.logs_tail()
        after_payload = get_after.json()
        assert after_payload["name"] == updated_name
        assert after_payload["description"] == updated_desc
        assert after_payload["system_prompt_files"] == updated_prompt_files
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_agents_order_put_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify /api/agents/order persists a full agent order update.

    Test flow:
    1. GET /api/agents to capture a stable baseline order.
    2. PUT /api/agents/order with a reordered full agent ID list.
    3. GET /api/agents and verify returned order matches the updated order.
    4. PUT baseline order back for cleanup.

    API endpoints:
    - GET /api/agents
    - PUT /api/agents/order
    """
    list_before = app_server.api_request("GET", "/api/agents")
    assert list_before.status_code == 200, app_server.logs_tail()
    agents_before = list_before.json().get("agents", [])
    assert isinstance(agents_before, list)
    assert len(agents_before) >= 2, "need at least two agents for reorder test"

    baseline_ids = [item["id"] for item in agents_before]
    reordered_ids = [baseline_ids[-1], *baseline_ids[:-1]]

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/agents/order",
            json={"agent_ids": reordered_ids},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("success") is True
        assert put_resp.json().get("agent_ids") == reordered_ids

        list_after = app_server.api_request("GET", "/api/agents")
        assert list_after.status_code == 200, app_server.logs_tail()
        after_ids = [
            item["id"] for item in list_after.json().get("agents", [])
        ]
        assert after_ids == reordered_ids
    finally:
        restore = app_server.api_request(
            "PUT",
            "/api/agents/order",
            json={"agent_ids": baseline_ids},
        )
        assert restore.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_api_agent_patch_toggle_enabled_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PATCH /api/agents/{agentId}/toggle updates persisted ``enabled``
      and can be read back from the agent profile.

    Test flow:
    1. POST a dedicated test agent (starts enabled).
    2. PATCH toggle with ``enabled`` false and GET /api/agents list to verify
       the summary row for that agent shows ``enabled`` false.
    3. PATCH toggle with ``enabled`` true and verify via list again.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - PATCH /api/agents/{agentId}/toggle
    - GET /api/agents
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_agent_toggle_01"

    def _enabled_from_list() -> bool | None:
        list_resp = app_server.api_request("GET", "/api/agents")
        assert list_resp.status_code == 200, app_server.logs_tail()
        for row in list_resp.json().get("agents", []):
            if row.get("id") == agent_id:
                return bool(row.get("enabled", True))
        return None

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Toggle agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        off = app_server.api_request(
            "PATCH",
            f"/api/agents/{agent_id}/toggle",
            json={"enabled": False},
        )
        assert off.status_code == 200, app_server.logs_tail()
        assert off.json().get("enabled") is False
        assert _enabled_from_list() is False

        on = app_server.api_request(
            "PATCH",
            f"/api/agents/{agent_id}/toggle",
            json={"enabled": True},
        )
        assert on.status_code == 200, app_server.logs_tail()
        assert on.json().get("enabled") is True
        assert _enabled_from_list() is True
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
