# -*- coding: utf-8 -*-
"""Integration tests for built-in tools API (scoped, no external keys)."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_tools_toggle_and_async_execution_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify agent-scoped tool PATCH endpoints toggle ``enabled`` and update
      ``async_execution`` with readback via GET list.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped tools list and pick the first built-in tool name.
    3. Record baseline ``enabled`` and ``async_execution`` from that tool.
    4. PATCH toggle twice (or once) to restore original ``enabled`` while
       asserting each response matches the flipped value.
    5. PATCH async_execution to the opposite value, GET list to confirm, then
       restore baseline async_execution.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/tools
    - PATCH /api/agents/{agentId}/tools/{tool_name}/toggle
    - PATCH /api/agents/{agentId}/tools/{tool_name}/async-execution
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_tools_01"
    base = f"/api/agents/{agent_id}/tools"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Scoped tools agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        list_resp = app_server.api_request("GET", base)
        assert list_resp.status_code == 200, app_server.logs_tail()
        tools = list_resp.json()
        assert isinstance(tools, list) and tools, app_server.logs_tail()
        tool_name = str(tools[0]["name"])
        baseline_enabled = bool(tools[0].get("enabled", True))
        baseline_async = bool(tools[0].get("async_execution", False))

        t1 = app_server.api_request(
            "PATCH",
            f"{base}/{tool_name}/toggle",
        )
        assert t1.status_code == 200, app_server.logs_tail()
        assert bool(t1.json().get("enabled")) is (not baseline_enabled)

        t2 = app_server.api_request(
            "PATCH",
            f"{base}/{tool_name}/toggle",
        )
        assert t2.status_code == 200, app_server.logs_tail()
        assert bool(t2.json().get("enabled")) is baseline_enabled

        target_async = not baseline_async
        a1 = app_server.api_request(
            "PATCH",
            f"{base}/{tool_name}/async-execution",
            json={"async_execution": target_async},
        )
        assert a1.status_code == 200, app_server.logs_tail()
        assert bool(a1.json().get("async_execution")) is target_async

        list_mid = app_server.api_request("GET", base)
        assert list_mid.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_mid.json()}
        assert bool(by_name[tool_name].get("async_execution")) is target_async

        a2 = app_server.api_request(
            "PATCH",
            f"{base}/{tool_name}/async-execution",
            json={"async_execution": baseline_async},
        )
        assert a2.status_code == 200, app_server.logs_tail()
        assert bool(a2.json().get("async_execution")) is baseline_async
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
