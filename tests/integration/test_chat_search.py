# -*- coding: utf-8 -*-
"""Search persisted conversation content through the real HTTP app."""

import json
from pathlib import Path

import pytest

from qwenpaw.app.chats.session import session_filename


@pytest.mark.integration
@pytest.mark.p1
def test_chat_search_content_pagination_and_agent_scope(app_server):
    """Unrelated titles still match body text within the selected agent."""
    agent_ids = ["search_http_alpha", "search_http_beta"]
    chats = []
    try:
        for agent_id in agent_ids:
            response = app_server.api_request(
                "POST",
                "/api/agents",
                json={"id": agent_id, "name": agent_id},
            )
            assert response.status_code == 201, app_server.logs_tail()
            workspace = Path(response.json()["workspace_dir"])
            for index in range(2):
                response = app_server.api_request(
                    "POST",
                    f"/api/agents/{agent_id}/chats",
                    json={
                        "name": f"Unrelated generated title {index}",
                        "session_id": f"search-http-{agent_id}-{index}",
                        "user_id": "search-user",
                        "channel": "console",
                    },
                )
                assert response.status_code == 200, app_server.logs_tail()
                chat = response.json()
                chats.append((agent_id, chat["id"]))
                snapshot = workspace / "sessions" / "console"
                snapshot.mkdir(parents=True, exist_ok=True)
                path = snapshot / session_filename(
                    chat["session_id"],
                    chat["user_id"],
                )
                path.write_text(
                    json.dumps(
                        {
                            "agent": {
                                "state": {
                                    "context": [
                                        {
                                            "id": f"message-{index}",
                                            "name": "user",
                                            "role": "user",
                                            "content": (
                                                "部署记录: retry-needle-731"
                                            ),
                                        },
                                    ],
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

        alpha_ids = {
            chat_id for owner, chat_id in chats if owner == agent_ids[0]
        }
        pages = []
        for offset in (0, 1):
            response = app_server.api_request(
                "POST",
                "/api/chats/search",
                headers={"X-Agent-Id": agent_ids[0]},
                json={
                    "query": "RETRY-NEEDLE-731",
                    "limit": 1,
                    "offset": offset,
                },
            )
            assert response.status_code == 200, app_server.logs_tail()
            page = response.json()
            assert page["total"] == 2
            assert page["has_more"] is (offset == 0)
            assert page["partial"] is False
            assert len(page["results"]) == 1
            result = page["results"][0]
            assert result["role"] == "user"
            assert "retry-needle-731" in result["snippet"]
            pages.append(result["chat"]["id"])
        assert set(pages) == alpha_ids

        response = app_server.api_request(
            "POST",
            f"/api/agents/{agent_ids[1]}/chats/search",
            json={"query": "部署记录"},
        )
        assert response.status_code == 200, app_server.logs_tail()
        beta_ids = {
            chat_id for owner, chat_id in chats if owner == agent_ids[1]
        }
        assert {
            hit["chat"]["id"] for hit in response.json()["results"]
        } == beta_ids

        archived_id = pages[0]
        response = app_server.api_request(
            "POST",
            f"/api/agents/{agent_ids[0]}/chats/{archived_id}/archive",
        )
        assert response.status_code == 200, app_server.logs_tail()
        response = app_server.api_request(
            "POST",
            f"/api/agents/{agent_ids[0]}/chats/search",
            json={"query": "retry-needle-731"},
        )
        assert response.status_code == 200, app_server.logs_tail()
        assert [hit["chat"]["id"] for hit in response.json()["results"]] == [
            pages[1],
        ]
    finally:
        for agent_id in agent_ids:
            app_server.api_request("DELETE", f"/api/agents/{agent_id}")
