# -*- coding: utf-8 -*-
"""Smoke tests for global /api/chats (CRUD, batch, isolation)."""
from __future__ import annotations


import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_api_chats_crud_and_agent_scoped_list(app_server) -> None:
    """Test purpose:
    - Verify core chat CRUD works correctly under a specific agent context.
    - Verify agent-scoped route (/api/agents/{agentId}/...) + header
      context target the same agent data.

    Test flow:
    1. POST /api/agents to create a test agent.
    2. POST /api/chats with X-Agent-Id to create a chat.
    3. GET /api/agents/{agentId}/chats and confirm the chat is visible.
    4. GET /api/chats/{chatId} to read history.
    5. PUT /api/chats/{chatId} to update the name.
    6. DELETE chat and test agent for cleanup.

    API endpoints:
    - POST /api/agents
    - POST /api/chats
    - GET /api/agents/{agentId}/chats
    - GET /api/chats/{chatId}
    - PUT /api/chats/{chatId}
    - DELETE /api/chats/{chatId}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_chats_01"
    headers = {"X-Agent-Id": agent_id}
    chat_id: str | None = None

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Chats smoke agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        post_chat = app_server.api_request(
            "POST",
            "/api/chats",
            headers=headers,
            json={
                "name": "Integration smoke chat",
                "session_id": "console:integ-user-1",
                "user_id": "integ-user-1",
                "channel": "console",
                "meta": {},
            },
        )
        assert post_chat.status_code == 200, app_server.logs_tail()
        spec = post_chat.json()
        chat_id = spec["id"]
        assert isinstance(chat_id, str) and chat_id
        assert spec["name"] == "Integration smoke chat"
        assert spec["session_id"] == "console:integ-user-1"
        assert spec["user_id"] == "integ-user-1"
        assert spec["channel"] == "console"

        scoped_list = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/chats",
        )
        assert scoped_list.status_code == 200, app_server.logs_tail()
        chats = scoped_list.json()
        assert isinstance(chats, list)
        ids = {c["id"] for c in chats}
        assert chat_id in ids

        get_hist = app_server.api_request(
            "GET",
            f"/api/chats/{chat_id}",
            headers=headers,
        )
        assert get_hist.status_code == 200, app_server.logs_tail()
        history = get_hist.json()
        assert "messages" in history and isinstance(history["messages"], list)
        assert "status" in history and isinstance(history["status"], str)

        put_chat = app_server.api_request(
            "PUT",
            f"/api/chats/{chat_id}",
            headers=headers,
            json={"name": "Integration smoke chat renamed"},
        )
        assert put_chat.status_code == 200, app_server.logs_tail()
        assert put_chat.json()["name"] == "Integration smoke chat renamed"
    finally:
        if chat_id is not None:
            app_server.api_request(
                "DELETE",
                f"/api/chats/{chat_id}",
                headers=headers,
            )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_chats_batch_delete(app_server) -> None:
    """Test purpose:
    - Verify batch-delete removes multiple chats in one request and
      they no longer appear in list results.

    Test flow:
    1. POST /api/agents to create a test agent.
    2. POST /api/chats twice (with X-Agent-Id) to create two chats.
    3. GET /api/chats and assert both chat IDs exist.
    4. POST /api/chats/batch-delete with both IDs.
    5. GET /api/chats again and assert both IDs are gone.
    6. Cleanup: delete test agent (chat IDs defensively in finally).

    API endpoints:
    - POST /api/agents
    - POST /api/chats
    - GET /api/chats
    - POST /api/chats/batch-delete
    - DELETE /api/chats/{chatId} (defensive cleanup in finally)
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_chats_batch_01"
    headers = {"X-Agent-Id": agent_id}
    chat_ids: list[str] = []

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Chats batch smoke agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        for idx in (1, 2):
            resp = app_server.api_request(
                "POST",
                "/api/chats",
                headers=headers,
                json={
                    "name": f"Batch chat {idx}",
                    "session_id": f"console:integ-batch-user-{idx}",
                    "user_id": f"integ-batch-user-{idx}",
                    "channel": "console",
                    "meta": {},
                },
            )
            assert resp.status_code == 200, app_server.logs_tail()
            chat_ids.append(resp.json()["id"])

        list_before = app_server.api_request(
            "GET",
            "/api/chats",
            headers=headers,
        )
        assert list_before.status_code == 200, app_server.logs_tail()
        before_ids = {item["id"] for item in list_before.json()}
        for chat_id in chat_ids:
            assert chat_id in before_ids

        batch_delete = app_server.api_request(
            "POST",
            "/api/chats/batch-delete",
            headers=headers,
            json=chat_ids,
        )
        assert batch_delete.status_code == 200, app_server.logs_tail()
        assert batch_delete.json().get("deleted") is True

        list_after = app_server.api_request(
            "GET",
            "/api/chats",
            headers=headers,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        after_ids = {item["id"] for item in list_after.json()}
        for chat_id in chat_ids:
            assert chat_id not in after_ids
    finally:
        for chat_id in chat_ids:
            cleanup_resp = app_server.api_request(
                "DELETE",
                f"/api/chats/{chat_id}",
                headers=headers,
            )
            assert cleanup_resp.status_code in (
                200,
                404,
            ), app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_api_chats_isolated_between_agents(app_server) -> None:
    """Test purpose:
    - Verify chat data is isolated per agent and does not leak across agents.
    - Verify both header-based and scoped chat listing honor agent boundaries.

    Test flow:
    1. Create two test agents (A/B).
    2. Create one chat under each agent with the same user filter key.
    3. List chats for each agent with ``user_id`` filter and verify only local
       chat IDs are present.
    4. Repeat listing via scoped routes to verify the same isolation behavior.
    5. Cleanup chats (defensive) and both agents.

    API endpoints:
    - POST /api/agents
    - POST /api/chats
    - GET /api/chats
    - GET /api/agents/{agentId}/chats
    - DELETE /api/chats/{chatId} (defensive cleanup in finally)
    - DELETE /api/agents/{agentId}
    """
    agent_a = "integ_iso_agent_a"
    agent_b = "integ_iso_agent_b"
    headers_a = {"X-Agent-Id": agent_a}
    headers_b = {"X-Agent-Id": agent_b}
    shared_user = "integ-isolation-user"
    chat_a_id: str | None = None
    chat_b_id: str | None = None

    create_a = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_a, "name": "Isolation agent A", "description": ""},
    )
    assert create_a.status_code == 201, app_server.logs_tail()
    create_b = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_b, "name": "Isolation agent B", "description": ""},
    )
    assert create_b.status_code == 201, app_server.logs_tail()

    try:
        chat_a = app_server.api_request(
            "POST",
            "/api/chats",
            headers=headers_a,
            json={
                "name": "Isolation chat A",
                "session_id": "console:iso-a",
                "user_id": shared_user,
                "channel": "console",
                "meta": {},
            },
        )
        assert chat_a.status_code == 200, app_server.logs_tail()
        chat_a_id = chat_a.json()["id"]

        chat_b = app_server.api_request(
            "POST",
            "/api/chats",
            headers=headers_b,
            json={
                "name": "Isolation chat B",
                "session_id": "console:iso-b",
                "user_id": shared_user,
                "channel": "console",
                "meta": {},
            },
        )
        assert chat_b.status_code == 200, app_server.logs_tail()
        chat_b_id = chat_b.json()["id"]

        list_a = app_server.api_request(
            "GET",
            "/api/chats",
            headers=headers_a,
            params={"user_id": shared_user},
        )
        assert list_a.status_code == 200, app_server.logs_tail()
        list_a_ids = {item["id"] for item in list_a.json()}
        assert chat_a_id in list_a_ids
        assert chat_b_id not in list_a_ids

        list_b = app_server.api_request(
            "GET",
            "/api/chats",
            headers=headers_b,
            params={"user_id": shared_user},
        )
        assert list_b.status_code == 200, app_server.logs_tail()
        list_b_ids = {item["id"] for item in list_b.json()}
        assert chat_b_id in list_b_ids
        assert chat_a_id not in list_b_ids

        scoped_a = app_server.api_request(
            "GET",
            f"/api/agents/{agent_a}/chats",
            params={"user_id": shared_user},
        )
        assert scoped_a.status_code == 200, app_server.logs_tail()
        scoped_a_ids = {item["id"] for item in scoped_a.json()}
        assert chat_a_id in scoped_a_ids
        assert chat_b_id not in scoped_a_ids

        scoped_b = app_server.api_request(
            "GET",
            f"/api/agents/{agent_b}/chats",
            params={"user_id": shared_user},
        )
        assert scoped_b.status_code == 200, app_server.logs_tail()
        scoped_b_ids = {item["id"] for item in scoped_b.json()}
        assert chat_b_id in scoped_b_ids
        assert chat_a_id not in scoped_b_ids
    finally:
        if chat_a_id is not None:
            app_server.api_request(
                "DELETE",
                f"/api/chats/{chat_a_id}",
                headers=headers_a,
            )
        if chat_b_id is not None:
            app_server.api_request(
                "DELETE",
                f"/api/chats/{chat_b_id}",
                headers=headers_b,
            )
        app_server.api_request("DELETE", f"/api/agents/{agent_a}")
        app_server.api_request("DELETE", f"/api/agents/{agent_b}")
