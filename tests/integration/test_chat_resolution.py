# -*- coding: utf-8 -*-
"""HTTP regression for cross-Agent and archived Console deep links."""

import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_chat_link_resolves_its_owner_and_preserves_archive_state(app_server):
    """Resolve metadata globally while history remains Agent-scoped."""
    agent_id = f"integ_chat_resolve_8101"
    headers = {f"X-Agent-Id": agent_id}
    chat_id = None
    created_agent = app_server.api_request(
        f"POST",
        f"/api/agents",
        json={f"id": agent_id, f"name": f"Chat resolver regression"},
    )
    assert created_agent.status_code == 201, app_server.logs_tail()

    try:
        created = app_server.api_request(
            f"POST",
            f"/api/chats",
            headers=headers,
            json={
                f"name": f"Linked conversation",
                f"session_id": f"console:integ-resolve-8101",
                f"user_id": f"integ-resolve-8101",
                f"channel": f"console",
            },
        )
        assert created.status_code == 200, app_server.logs_tail()
        chat_id = created.json()[f"id"]
        query = {f"chat_id": chat_id, f"current_agent_id": f"default"}
        resolved = app_server.api_request(
            f"GET",
            f"/api/chats/resolve",
            params=query,
            headers={f"X-Agent-Id": f"default"},
        )
        assert resolved.status_code == 200, app_server.logs_tail()
        assert resolved.json()[f"agent_id"] == agent_id
        assert resolved.json()[f"chat"] == created.json()

        wrong_owner = app_server.api_request(
            f"GET",
            f"/api/chats/{chat_id}",
            headers={f"X-Agent-Id": f"default"},
        )
        assert wrong_owner.status_code == 404, app_server.logs_tail()
        history = app_server.api_request(
            f"GET",
            f"/api/chats/{chat_id}",
            headers=headers,
        )
        assert history.status_code == 200, app_server.logs_tail()

        archived = app_server.api_request(
            f"POST",
            f"/api/chats/{chat_id}/archive",
            headers=headers,
        )
        assert archived.status_code == 200, app_server.logs_tail()
        archived_link = app_server.api_request(
            f"GET",
            f"/api/chats/resolve",
            params=query,
        )
        assert archived_link.status_code == 200, app_server.logs_tail()
        assert archived_link.json()[f"agent_id"] == agent_id
        assert archived_link.json()[f"chat"][f"archived"] is True
    finally:
        if chat_id:
            app_server.api_request(
                f"DELETE",
                f"/api/chats/{chat_id}",
                headers=headers,
            )
        app_server.api_request(f"DELETE", f"/api/agents/{agent_id}")
