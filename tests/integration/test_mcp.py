# -*- coding: utf-8 -*-
"""Integration tests for MCP client APIs."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_mcp_create_get_list_delete(app_server) -> None:
    """Test purpose:
    - Verify MCP client basic lifecycle in one agent workspace.

    Test flow:
    1. Create a test agent.
    2. POST /api/mcp to create one MCP client.
    3. GET /api/mcp and GET /api/mcp/{client_key} to verify presence.
    4. DELETE /api/mcp/{client_key}.
    5. GET /api/mcp and verify client is removed.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/mcp
    - GET /api/mcp
    - GET /api/mcp/{client_key}
    - DELETE /api/mcp/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_crud_01"
    headers = {"X-Agent-Id": agent_id}
    client_key = "integ_mcp_client_01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "MCP CRUD agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_client = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json={
                "client_key": client_key,
                "client": {
                    "name": "integration mcp client",
                    "description": "created by integration tests",
                    "enabled": True,
                    "transport": "stdio",
                    "command": "echo",
                    "args": ["mcp"],
                },
            },
        )
        assert create_client.status_code == 201, app_server.logs_tail()
        created = create_client.json()
        assert created.get("key") == client_key
        assert created.get("name") == "integration mcp client"

        list_clients = app_server.api_request(
            "GET",
            "/api/mcp",
            headers=headers,
        )
        assert list_clients.status_code == 200, app_server.logs_tail()
        keys = {item["key"] for item in list_clients.json()}
        assert client_key in keys

        get_client = app_server.api_request(
            "GET",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        assert get_client.status_code == 200, app_server.logs_tail()
        assert get_client.json().get("key") == client_key

        delete_client = app_server.api_request(
            "DELETE",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        assert delete_client.status_code == 200, app_server.logs_tail()

        list_after_delete = app_server.api_request(
            "GET",
            "/api/mcp",
            headers=headers,
        )
        assert list_after_delete.status_code == 200, app_server.logs_tail()
        keys_after = {item["key"] for item in list_after_delete.json()}
        assert client_key not in keys_after
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_mcp_toggle_enabled(app_server) -> None:
    """Test purpose:
    - Verify MCP toggle endpoint flips ``enabled`` state and persists.

    Test flow:
    1. Create a test agent and one MCP client with enabled=True.
    2. PATCH /api/mcp/toggle/{client_key} and assert enabled=False.
    3. GET /api/mcp/{client_key} and verify enabled=False persisted.
    4. PATCH again and verify enabled=True.
    5. Cleanup client and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/mcp
    - PATCH /api/mcp/toggle/{client_key}
    - GET /api/mcp/{client_key}
    - DELETE /api/mcp/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_toggle_01"
    headers = {"X-Agent-Id": agent_id}
    client_key = "integ_mcp_toggle_client"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "MCP toggle agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_client = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json={
                "client_key": client_key,
                "client": {
                    "name": "toggle mcp client",
                    "enabled": True,
                    "transport": "stdio",
                    "command": "echo",
                },
            },
        )
        assert create_client.status_code == 201, app_server.logs_tail()
        assert create_client.json().get("enabled") is True

        toggle_1 = app_server.api_request(
            "PATCH",
            f"/api/mcp/toggle/{client_key}",
            headers=headers,
        )
        assert toggle_1.status_code == 200, app_server.logs_tail()
        assert toggle_1.json().get("enabled") is False

        get_after_toggle_1 = app_server.api_request(
            "GET",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        assert get_after_toggle_1.status_code == 200, app_server.logs_tail()
        assert get_after_toggle_1.json().get("enabled") is False

        toggle_2 = app_server.api_request(
            "PATCH",
            f"/api/mcp/toggle/{client_key}",
            headers=headers,
        )
        assert toggle_2.status_code == 200, app_server.logs_tail()
        assert toggle_2.json().get("enabled") is True
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_mcp_tools_returns_empty_for_disabled_client(app_server) -> None:
    """Test purpose:
    - Verify /tools endpoint returns empty list when MCP client is disabled.

    Test flow:
    1. Create a test agent.
    2. Create a disabled MCP client.
    3. GET /api/mcp/tools/{client_key} and assert empty list.
    4. Cleanup client and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/mcp
    - GET /api/mcp/tools/{client_key}
    - DELETE /api/mcp/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_tools_01"
    headers = {"X-Agent-Id": agent_id}
    client_key = "integ_mcp_disabled_tools_client"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "MCP tools agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_client = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json={
                "client_key": client_key,
                "client": {
                    "name": "disabled mcp client",
                    "enabled": False,
                    "transport": "stdio",
                    "command": "echo",
                },
            },
        )
        assert create_client.status_code == 201, app_server.logs_tail()

        tools_resp = app_server.api_request(
            "GET",
            f"/api/mcp/tools/{client_key}",
            headers=headers,
        )
        assert tools_resp.status_code == 200, app_server.logs_tail()
        assert tools_resp.json() == []
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_scoped_path_get_client(app_server) -> None:
    """Test purpose:
    - Verify MCP client can be fetched via ``/api/agents/{agentId}/mcp/...``
      without ``X-Agent-Id`` header (path-derived agent context).

    Test flow:
    1. Create a test agent.
    2. POST /api/mcp with header to create a client (same as existing tests).
    3. GET /api/agents/{agentId}/mcp/{client_key} without header.
    4. Cleanup via header-based DELETE and agent delete.

    API endpoints:
    - POST /api/agents
    - POST /api/mcp
    - GET /api/agents/{agentId}/mcp/{client_key}
    - DELETE /api/mcp/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_scoped_get_01"
    headers = {"X-Agent-Id": agent_id}
    client_key = "integ_mcp_scoped_get_client"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "MCP scoped GET agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_client = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json={
                "client_key": client_key,
                "client": {
                    "name": "scoped path get client",
                    "enabled": True,
                    "transport": "stdio",
                    "command": "echo",
                    "args": ["scoped"],
                },
            },
        )
        assert create_client.status_code == 201, app_server.logs_tail()

        scoped_get = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/mcp/{client_key}",
        )
        assert scoped_get.status_code == 200, app_server.logs_tail()
        assert scoped_get.json().get("key") == client_key
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_mcp_create_duplicate_client_rejected(app_server) -> None:
    """Test purpose:
    - Verify creating an MCP client with duplicated ``client_key`` is rejected.

    Test flow:
    1. Create a dedicated test agent.
    2. POST /api/mcp once with a fixed client_key (expect 201).
    3. POST /api/mcp again with the same client_key (expect 400).
    4. Assert error detail includes guidance about existing client.
    5. Cleanup client and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/mcp
    - DELETE /api/mcp/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_duplicate_01"
    headers = {"X-Agent-Id": agent_id}
    client_key = "integ_mcp_dup_client"
    payload = {
        "client_key": client_key,
        "client": {
            "name": "duplicate check client",
            "enabled": True,
            "transport": "stdio",
            "command": "echo",
            "args": ["dup"],
        },
    }

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "MCP duplicate agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        first = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json=payload,
        )
        assert first.status_code == 201, app_server.logs_tail()

        second = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json=payload,
        )
        assert second.status_code == 400, app_server.logs_tail()
        assert "already exists" in second.json().get("detail", "")
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_mcp_missing_client_paths_return_404(app_server) -> None:
    """Test purpose:
    - Verify MCP endpoints consistently return 404 for unknown ``client_key``.

    Test flow:
    1. Create a dedicated test agent.
    2. Call GET /api/mcp/{client_key}, PATCH /toggle/{client_key}, DELETE,
       and GET /tools/{client_key} using a missing client_key.
    3. Assert all responses are 404 with error details.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/mcp/{client_key}
    - PATCH /api/mcp/toggle/{client_key}
    - DELETE /api/mcp/{client_key}
    - GET /api/mcp/tools/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_missing_01"
    headers = {"X-Agent-Id": agent_id}
    missing_key = "integ_mcp_missing_key"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "MCP missing agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        get_resp = app_server.api_request(
            "GET",
            f"/api/mcp/{missing_key}",
            headers=headers,
        )
        assert get_resp.status_code == 404, app_server.logs_tail()
        assert "detail" in get_resp.json()

        toggle_resp = app_server.api_request(
            "PATCH",
            f"/api/mcp/toggle/{missing_key}",
            headers=headers,
        )
        assert toggle_resp.status_code == 404, app_server.logs_tail()
        assert "detail" in toggle_resp.json()

        delete_resp = app_server.api_request(
            "DELETE",
            f"/api/mcp/{missing_key}",
            headers=headers,
        )
        assert delete_resp.status_code == 404, app_server.logs_tail()
        assert "detail" in delete_resp.json()

        tools_resp = app_server.api_request(
            "GET",
            f"/api/mcp/tools/{missing_key}",
            headers=headers,
        )
        assert tools_resp.status_code == 404, app_server.logs_tail()
        assert "detail" in tools_resp.json()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_update_client_put_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify MCP client update endpoint persists mutable fields and supports
      deterministic readback.

    Test flow:
    1. Create a dedicated test agent and one MCP client.
    2. PUT /api/mcp/{client_key} with updated name/description/enabled fields.
    3. GET /api/mcp/{client_key} and verify updated fields.
    4. Cleanup client and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/mcp
    - PUT /api/mcp/{client_key}
    - GET /api/mcp/{client_key}
    - DELETE /api/mcp/{client_key}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mcp_update_01"
    headers = {"X-Agent-Id": agent_id}
    client_key = "integ_mcp_update_client"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "MCP update agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_client = app_server.api_request(
            "POST",
            "/api/mcp",
            headers=headers,
            json={
                "client_key": client_key,
                "client": {
                    "name": "update before",
                    "description": "before update",
                    "enabled": True,
                    "transport": "stdio",
                    "command": "echo",
                    "args": ["before"],
                },
            },
        )
        assert create_client.status_code == 201, app_server.logs_tail()

        update_resp = app_server.api_request(
            "PUT",
            f"/api/mcp/{client_key}",
            headers=headers,
            json={
                "name": "update after",
                "description": "after update",
                "enabled": False,
                "args": ["after"],
            },
        )
        assert update_resp.status_code == 200, app_server.logs_tail()
        update_payload = update_resp.json()
        assert update_payload.get("key") == client_key
        assert update_payload.get("name") == "update after"
        assert update_payload.get("description") == "after update"
        assert update_payload.get("enabled") is False

        get_after = app_server.api_request(
            "GET",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        get_payload = get_after.json()
        assert get_payload.get("name") == "update after"
        assert get_payload.get("description") == "after update"
        assert get_payload.get("enabled") is False
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/mcp/{client_key}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_mcp_agent_scoped_routes_update_toggle_delete(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped MCP routes support create/update/toggle/delete flow
      under /api/agents/{agentId}/mcp.

    Test flow:
    1. Create a dedicated test agent.
    2. POST scoped MCP client.
    3. PUT scoped client and verify updated fields.
    4. PATCH scoped toggle and verify enabled flips.
    5. DELETE scoped client and verify it is removed from scoped list.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/mcp
    - PUT /api/agents/{agentId}/mcp/{client_key}
    - PATCH /api/agents/{agentId}/mcp/toggle/{client_key}
    - DELETE /api/agents/{agentId}/mcp/{client_key}
    - GET /api/agents/{agentId}/mcp
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_mcp_01"
    client_key = "integ_scoped_mcp_client_01"
    scoped_base = f"/api/agents/{agent_id}/mcp"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Scoped MCP agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_client = app_server.api_request(
            "POST",
            scoped_base,
            json={
                "client_key": client_key,
                "client": {
                    "name": "scoped mcp before",
                    "description": "before update",
                    "enabled": True,
                    "transport": "stdio",
                    "command": "echo",
                },
            },
        )
        assert create_client.status_code == 201, app_server.logs_tail()
        assert create_client.json().get("key") == client_key

        update_client = app_server.api_request(
            "PUT",
            f"{scoped_base}/{client_key}",
            json={
                "name": "scoped mcp after",
                "description": "after update",
                "enabled": False,
                "args": ["scoped"],
            },
        )
        assert update_client.status_code == 200, app_server.logs_tail()
        assert update_client.json().get("name") == "scoped mcp after"
        assert update_client.json().get("enabled") is False

        toggle_client = app_server.api_request(
            "PATCH",
            f"{scoped_base}/toggle/{client_key}",
        )
        assert toggle_client.status_code == 200, app_server.logs_tail()
        assert toggle_client.json().get("enabled") is True

        delete_client = app_server.api_request(
            "DELETE",
            f"{scoped_base}/{client_key}",
        )
        assert delete_client.status_code == 200, app_server.logs_tail()

        list_after = app_server.api_request("GET", scoped_base)
        assert list_after.status_code == 200, app_server.logs_tail()
        keys_after = {item["key"] for item in list_after.json()}
        assert client_key not in keys_after
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
