# -*- coding: utf-8 -*-
"""HTTP smoke tests for agent-scoped chats endpoints."""
from __future__ import annotations


import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_api_agent_scoped_chats_create_list_batch_delete(app_server) -> None:
    """Test purpose:
    - Verify chats can be created, listed, and batch-deleted using only
      agent-scoped paths (no ``X-Agent-Id`` header).

    Test flow:
    1. POST /api/agents to create a test agent.
    2. POST /api/agents/{agentId}/chats twice to create two chats.
    3. GET /api/agents/{agentId}/chats and assert both IDs are listed.
    4. POST /api/agents/{agentId}/chats/batch-delete with both IDs.
    5. GET the scoped list again and assert both IDs are gone.
    6. Defensive per-chat DELETE and DELETE agent in finally.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/chats
    - GET /api/agents/{agentId}/chats
    - POST /api/agents/{agentId}/chats/batch-delete
    - DELETE /api/agents/{agentId}/chats/{chatId}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_chats_batch_01"
    base = f"/api/agents/{agent_id}"
    chat_ids: list[str] = []

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped chats batch agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        for idx in (1, 2):
            resp = app_server.api_request(
                "POST",
                f"{base}/chats",
                json={
                    "name": f"Scoped batch chat {idx}",
                    "session_id": f"console:integ-scoped-batch-{idx}",
                    "user_id": f"integ-scoped-batch-user-{idx}",
                    "channel": "console",
                    "meta": {},
                },
            )
            assert resp.status_code == 200, app_server.logs_tail()
            chat_ids.append(resp.json()["id"])

        list_before = app_server.api_request("GET", f"{base}/chats")
        assert list_before.status_code == 200, app_server.logs_tail()
        before_ids = {item["id"] for item in list_before.json()}
        for chat_id in chat_ids:
            assert chat_id in before_ids

        batch_delete = app_server.api_request(
            "POST",
            f"{base}/chats/batch-delete",
            json=chat_ids,
        )
        assert batch_delete.status_code == 200, app_server.logs_tail()
        assert batch_delete.json().get("deleted") is True

        list_after = app_server.api_request("GET", f"{base}/chats")
        assert list_after.status_code == 200, app_server.logs_tail()
        after_ids = {item["id"] for item in list_after.json()}
        for chat_id in chat_ids:
            assert chat_id not in after_ids
    finally:
        for chat_id in chat_ids:
            cleanup = app_server.api_request(
                "DELETE",
                f"{base}/chats/{chat_id}",
            )
            assert cleanup.status_code in (200, 404), app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_api_agent_scoped_chat_put_get_delete(app_server) -> None:
    """Test purpose:
    - Verify a single chat can be updated, read back, and deleted via
      agent-scoped chat routes.

    Test flow:
    1. POST /api/agents then POST /api/agents/{agentId}/chats to create a chat.
    2. PUT /api/agents/{agentId}/chats/{chatId} to rename it.
    3. GET /api/agents/{agentId}/chats/{chatId}; assert history + name
       consistency on a follow-up list read.
    4. DELETE /api/agents/{agentId}/chats/{chatId}; 404 on repeat delete.
    5. DELETE the test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/chats
    - PUT /api/agents/{agentId}/chats/{chatId}
    - GET /api/agents/{agentId}/chats/{chatId}
    - DELETE /api/agents/{agentId}/chats/{chatId}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_chat_crud_01"
    base = f"/api/agents/{agent_id}"
    chat_id: str | None = None

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped single chat agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        post_chat = app_server.api_request(
            "POST",
            f"{base}/chats",
            json={
                "name": "Scoped chat original",
                "session_id": "console:integ-scoped-crud",
                "user_id": "integ-scoped-crud-user",
                "channel": "console",
                "meta": {},
            },
        )
        assert post_chat.status_code == 200, app_server.logs_tail()
        chat_id = post_chat.json()["id"]
        assert isinstance(chat_id, str) and chat_id

        put_chat = app_server.api_request(
            "PUT",
            f"{base}/chats/{chat_id}",
            json={"name": "Scoped chat renamed"},
        )
        assert put_chat.status_code == 200, app_server.logs_tail()
        assert put_chat.json()["name"] == "Scoped chat renamed"

        get_hist = app_server.api_request("GET", f"{base}/chats/{chat_id}")
        assert get_hist.status_code == 200, app_server.logs_tail()
        history = get_hist.json()
        assert "messages" in history and isinstance(history["messages"], list)
        assert "status" in history and isinstance(history["status"], str)

        list_chats = app_server.api_request("GET", f"{base}/chats")
        assert list_chats.status_code == 200, app_server.logs_tail()
        names_by_id = {c["id"]: c.get("name") for c in list_chats.json()}
        assert names_by_id.get(chat_id) == "Scoped chat renamed"

        del_first = app_server.api_request("DELETE", f"{base}/chats/{chat_id}")
        assert del_first.status_code == 200, app_server.logs_tail()
        assert del_first.json().get("deleted") is True

        del_second = app_server.api_request(
            "DELETE",
            f"{base}/chats/{chat_id}",
        )
        assert del_second.status_code == 404, app_server.logs_tail()
        chat_id = None
    finally:
        if chat_id is not None:
            app_server.api_request("DELETE", f"{base}/chats/{chat_id}")
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
